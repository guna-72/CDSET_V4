"""V39: bugs found by running real open-source projects through the pipeline."""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("CHAOS_TUTOR_DB_PATH", tempfile.mktemp(suffix=".db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import analyzer, api, db, diagnosis, git_intake, orchestrator, sandbox, tutor  # noqa: E402
from app.http_framework import HTTPError  # noqa: E402

db.init_db()
ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_ZIP = ROOT / "sample_projects" / "mini_task_api.zip"

EXP = {"name": "Malformed request body", "category": "http", "target": "http_api",
       "fault_type": "malformed_request", "expected_behavior": "400"}


def detect(outcome, stderr="", exit_code=1, ready=False, reasoning="the target service never became reachable in the sandbox, independent of the injected fault"):
    return {"outcome": outcome, "reasoning": reasoning,
            "evidence": {"stderr": stderr, "exit_code": exit_code, "service_ready": ready}}


def diag(stderr, exit_code=1, reasoning=None):
    d = detect("TARGET_UNREACHABLE", stderr, exit_code, **({"reasoning": reasoning} if reasoning else {}))
    return diagnosis._rule_based_diagnose(EXP, d, {"framework": "x"})


class TestStartupFailureDiagnosis(unittest.TestCase):
    def test_missing_python_package(self):
        out = diag("Traceback (most recent call last):\n  File \"app.py\", line 3, in <module>\n"
                   "    import flask_cors\nModuleNotFoundError: No module named 'flask_cors'\n")
        self.assertIn("'flask_cors' is not installed", out["failure"])
        self.assertIn("pip install", out["recommended_fix"])
        self.assertTrue(out["setup_issue"])
        self.assertIn("nothing was tested", out["impact"])

    def test_missing_submodule_names_the_top_level_package(self):
        out = diag("ModuleNotFoundError: No module named 'yaml.constructor'")
        self.assertIn("'yaml'", out["failure"])

    def test_missing_node_module(self):
        out = diag("node:internal/modules/cjs/loader:1386\n  throw err;\n  ^\n\n"
                   "Error: Cannot find module 'express'\nRequire stack:\n- /x/index.js\n")
        self.assertIn("'express'", out["failure"])
        self.assertIn("npm install", out["recommended_fix"])

    def test_missing_local_node_file_is_not_an_npm_problem(self):
        out = diag("Error: Cannot find module './routes/users'\n")
        self.assertIn("missing", out["failure"])
        self.assertNotIn("npm install", out["recommended_fix"])

    def test_port_in_use_posix_node_and_windows_wording(self):
        for text in ("Error: listen EADDRINUSE: address already in use :::5000",
                     "OSError: [Errno 98] Address already in use",
                     "OSError: [WinError 10048] Only one usage of each socket address (protocol/network address/port) is normally permitted"):
            with self.subTest(text=text):
                out = diag(text)
                self.assertIn("port", out["failure"])
                self.assertIn("PORT", out["recommended_fix"])

    def test_syntax_error(self):
        out = diag("  File \"app.py\", line 4\n    def x(:\n          ^\nSyntaxError: invalid syntax\n")
        self.assertIn("syntax error", out["failure"])

    def test_other_startup_exception_names_its_type(self):
        out = diag("Traceback (most recent call last):\n  File \"app.py\", line 9, in <module>\nKeyError: 'DATABASE_URL'\n")
        self.assertIn("KeyError", out["failure"])
        self.assertNotIn("handled", out["root_cause"])

    def test_silent_nonzero_exit(self):
        out = diag("", exit_code=3)
        self.assertIn("code 3", out["root_cause"])

    def test_running_but_never_listening_points_at_PORT(self):
        out = diag("", exit_code=None)
        self.assertIn("never began listening", out["failure"])
        self.assertIn("PORT", out["recommended_fix"])

    def test_sandbox_limit_is_not_blamed_on_the_project(self):
        out = diag("", exit_code=None, reasoning="never reachable. The service failed to start because the sandbox hit a process/thread limit (not because of the injected fault)")
        self.assertIn("not a problem in the project", out["root_cause"])

    def test_never_claims_the_fault_was_handled(self):
        out = diag("ModuleNotFoundError: No module named 'x'")
        blob = " ".join(str(v) for v in out.values()).lower()
        for bad in ("no negative impact", "handled the way", "no change needed", "already matches"):
            self.assertNotIn(bad, blob)

    def test_llm_is_not_consulted_for_setup_problems(self):
        real_enabled, real_llm = diagnosis.llm_providers.diagnosis_enabled, diagnosis._llm_diagnose
        calls = []
        diagnosis.llm_providers.diagnosis_enabled = lambda: True
        # diagnose_run swallows exceptions from the LLM path, so raising here
        # would be invisible - record the call instead.
        diagnosis._llm_diagnose = lambda *a, **k: calls.append(1) or {"method": "llm", "evidence": []}
        try:
            out = diagnosis.diagnose_run(EXP, detect("TARGET_UNREACHABLE", "ModuleNotFoundError: No module named 'x'"), {})
            self.assertEqual(calls, [], "LLM must not be called for TARGET_UNREACHABLE")
            self.assertEqual(out["method"], "rule_based")
            diagnosis.diagnose_run(EXP, detect("APPLICATION_FAILURE", "ValueError: x", 1, True, "crash"), {})
            self.assertEqual(calls, [1], "other outcomes must still use the LLM when enabled")
        finally:
            diagnosis.llm_providers.diagnosis_enabled, diagnosis._llm_diagnose = real_enabled, real_llm


class TestLongTracebacks(unittest.TestCase):
    def test_exception_at_the_end_of_a_long_traceback_is_still_found(self):
        frames = "".join(f'  File "/app/lib/mod{i}.py", line {i}, in handler_{i}\n    return call_{i}(request)\n' for i in range(120))
        stderr = "Traceback (most recent call last):\n" + frames + "ValueError: invalid literal for int() with base 10: 'abc'\n"
        self.assertGreater(len(stderr), 6000)
        out = diagnosis._rule_based_diagnose(EXP, detect("APPLICATION_FAILURE", stderr, 1, True, "app crashed"), {})
        self.assertIn("ValueError", out["root_cause"])
        self.assertTrue(any("ValueError" in e for e in out["evidence"]))


class TestTutorForSetupProblems(unittest.TestCase):
    def test_explanation_is_a_problem_to_fix_not_a_pass(self):
        d = detect("TARGET_UNREACHABLE", "ModuleNotFoundError: No module named 'flask'")
        dg = diagnosis._rule_based_diagnose(EXP, d, {})
        e = tutor.explain(EXP, d, dg)
        self.assertTrue(e["is_problem"]); self.assertTrue(e["setup_issue"])
        self.assertTrue(e["what_happened"].startswith("Service failed to start"))
        self.assertNotIn("No failure", e["what_happened"])
        self.assertIn("pip install", e["prevention"])

    def test_passing_run_is_unchanged(self):
        d = detect("PASSED", "", 0, True, "handled")
        dg = diagnosis._rule_based_diagnose(EXP, d, {})
        e = tutor.explain(EXP, d, dg)
        self.assertFalse(e["is_problem"]); self.assertFalse(e["setup_issue"])
        self.assertIn("no change needed", e["prevention"])

    def test_quiz_does_not_ask_why_an_untested_run_passed(self):
        d = detect("TARGET_UNREACHABLE", "ModuleNotFoundError: No module named 'flask'")
        q = tutor.generate_question(EXP, d, diagnosis._rule_based_diagnose(EXP, d, {}))
        self.assertNotIn("without exposing a weakness", q["question"])
        self.assertIn("failed to start", q["question"])
        self.assertTrue(tutor.evaluate_answer(q, "fail fast with a startup check")["correct"])
        self.assertTrue(tutor.evaluate_answer(q, "verify dependencies are installed")["correct"])


def _tree(files):
    d = tempfile.mkdtemp()
    for rel, text in files.items():
        p = pathlib.Path(d, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


class TestPythonEntrypointChoice(unittest.TestCase):
    """Real project: miguelgrinberg/microblog reported config.py as its entry."""

    def pick(self, files, sig="app.run"):
        d = _tree(files)
        self.addCleanup(shutil.rmtree, d, True)
        return analyzer._find_python_entrypoint(d, sorted(files), sig)

    def test_microblog_layout_picks_the_module_that_builds_the_app(self):
        self.assertEqual(self.pick({
            "config.py": "import os\nclass Config:\n    SECRET='x'\n",
            "microblog.py": "from app import create_app, db\napp = create_app()\n",
            "tests.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): pass\n",
            "app/__init__.py": "def create_app():\n    pass\n",
        }), "microblog.py")

    def test_config_settings_and_tests_are_never_preferred(self):
        self.assertEqual(self.pick({"config.py": "X=1\n", "settings.py": "Y=2\n", "tests.py": "pass\n", "zeta.py": "print(1)\n"}), "zeta.py")

    def test_main_block_beats_plain_module(self):
        self.assertEqual(self.pick({"a_helpers.py": "def f(): pass\n", "z_tool.py": "print('x')\nif __name__ == '__main__':\n    print(1)\n"}), "z_tool.py")

    def test_root_level_beats_nested(self):
        self.assertEqual(self.pick({"pkg/sub/service.py": "from flask import Flask\napp = Flask(__name__)\n",
                                    "service.py": "from flask import Flask\napp = Flask(__name__)\n"}), "service.py")

    def test_named_entrypoints_still_win(self):
        self.assertEqual(self.pick({"app.py": "app.run()\n", "microblog.py": "app = create_app()\n"}), "app.py")

    def test_unparseable_files_do_not_crash(self):
        self.assertEqual(self.pick({"broken.py": "def x(:\n", "ok.py": "print(1)\n"}), "ok.py")


class TestIdeTestRunners(unittest.TestCase):
    def _ws(self, files):
        src = _tree(files)
        self.addCleanup(shutil.rmtree, src, True)
        ws = sandbox.make_workspace(src, "t39")
        self.addCleanup(sandbox.destroy_workspace, ws)
        return ws

    def _run_like_ide(self, ws):
        argv = api._python_test_argv()
        result = sandbox.run_in_sandbox(argv, ws, timeout=60)
        if "pytest" in argv and result.exit_code == 5:
            result = api._python_unittest_fallback(sandbox, ws, result)
        return result

    @unittest.skipUnless(__import__("importlib").util.find_spec("pytest"), "pytest not installed")
    def test_unittest_style_tests_py_is_found_when_pytest_collects_nothing(self):
        ws = self._ws({"tests.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.assertTrue(True)\n    def test_b(self): self.assertEqual(1, 1)\n"})
        r = self._run_like_ide(ws)
        self.assertEqual(r.exit_code, 0)
        self.assertIn("Ran 2 tests", (r.stdout or "") + (r.stderr or ""))

    @unittest.skipUnless(__import__("importlib").util.find_spec("pytest"), "pytest not installed")
    def test_a_failing_unittest_is_a_real_failure_not_no_tests(self):
        ws = self._ws({"tests.py": "import unittest\nclass T(unittest.TestCase):\n    def test_a(self): self.assertEqual(1, 2)\n"})
        r = self._run_like_ide(ws)
        self.assertEqual(r.exit_code, 1)

    @unittest.skipUnless(__import__("importlib").util.find_spec("pytest"), "pytest not installed")
    def test_no_tests_at_all_still_reports_exit_5(self):
        ws = self._ws({"app.py": "print('hi')\n"})
        self.assertEqual(self._run_like_ide(ws).exit_code, 5)

    def test_node_test_argv_only_adds_jest_flag_for_jest(self):
        def argv(script):
            d = pathlib.Path(_tree({"package.json": json.dumps({"scripts": {"test": script}} if script is not None else {"name": "x"}),
                                    "node_modules/.keep": ""}))
            self.addCleanup(shutil.rmtree, d, True)
            return api._node_test_argv(d)
        self.assertEqual(argv("jest"), ["npm", "test", "--", "--runInBand"])
        self.assertEqual(argv("jest --coverage"), ["npm", "test", "--", "--runInBand"])
        self.assertEqual(argv("jest --runInBand"), ["npm", "test"])          # not duplicated
        self.assertEqual(argv("mocha"), ["npm", "test"])                    # mocha rejects the flag
        self.assertEqual(argv("vitest run"), ["npm", "test"])
        self.assertEqual(argv("node --test"), ["npm", "test"])
        for bad in (None, "", 'echo "Error: no test specified" && exit 1'):
            with self.subTest(script=bad):
                with self.assertRaises(HTTPError):
                    argv(bad)

    def test_node_test_without_package_json_is_a_clear_error(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        with self.assertRaises(HTTPError):
            api._node_test_argv(d)

    def test_node_test_without_node_modules_says_to_run_npm_install(self):
        d = pathlib.Path(_tree({"package.json": json.dumps({"scripts": {"test": "jest"}})}))
        self.addCleanup(shutil.rmtree, d, True)
        with self.assertRaises(HTTPError) as cm:
            api._node_test_argv(d)
        self.assertIn("npm install", str(cm.exception))
        self.assertIn(str(d), str(cm.exception))

    def test_express_without_node_modules_gets_an_actionable_reason(self):
        d = _tree({"package.json": json.dumps({"dependencies": {"express": "^4"}, "main": "index.js"}),
                   "index.js": "const app=require('express')();app.listen(process.env.PORT)\n"})
        self.addCleanup(shutil.rmtree, d, True)
        prof = analyzer.analyze_project(d)
        self.assertEqual(prof["execution_status"], "PARTIALLY_SUPPORTED")
        reason = prof.get("execution_status_reason") or prof.get("entrypoint", {}).get("reason") or json.dumps(prof)
        self.assertIn("npm install", reason)
        self.assertIn(d, reason)
        self.assertNotIn("no network access", reason)
        os.makedirs(os.path.join(d, "node_modules"))                       # user ran npm install
        self.assertEqual(analyzer.analyze_project(d)["execution_status"], "SUPPORTED")


class TestWindowsCommandResolution(unittest.TestCase):
    def setUp(self):
        self._saved = (sandbox._windows, sandbox._resolve_executable)
        self.addCleanup(lambda: setattr(sandbox, "_windows", self._saved[0]) or setattr(sandbox, "_resolve_executable", self._saved[1]))

    def test_bare_npm_is_resolved_to_its_cmd_file_on_windows(self):
        sandbox._windows = lambda: True
        sandbox._resolve_executable = lambda c: r"C:\Program Files\nodejs\npm.CMD" if c == "npm" else None
        argv = sandbox._build_argv(["npm", "test", "--", "--runInBand"])[0]
        self.assertEqual(argv, [r"C:\Program Files\nodejs\npm.CMD", "test", "--", "--runInBand"])

    def test_unresolvable_commands_are_left_alone(self):
        sandbox._windows = lambda: True
        sandbox._resolve_executable = lambda c: None
        self.assertEqual(sandbox._build_argv(["nosuchtool", "x"])[0], ["nosuchtool", "x"])

    def test_non_windows_is_unchanged(self):
        sandbox._windows = lambda: False
        sandbox._resolve_executable = lambda c: "/usr/bin/whatever"
        self.assertEqual(sandbox._build_argv(["npm", "test"])[0], ["npm", "test"])

    def test_node_still_gets_its_heap_flag(self):
        sandbox._windows = lambda: True
        sandbox._resolve_executable = lambda c: r"C:\nodejs\node.exe"
        argv = sandbox._build_argv(["node", "app.js"])[0]
        self.assertEqual(argv, [r"C:\nodejs\node.exe", "--max-old-space-size=256", "app.js"])


@unittest.skipUnless(PY_ZIP.exists(), "sample project missing")
class TestUnrunnableProjectsAreBlockedUpFront(unittest.TestCase):
    def setUp(self):
        self.p = orchestrator.create_project(str(PY_ZIP), "gate")
        self.addCleanup(git_intake.remove_tree, self.p["storage_path"])
        self.profile = orchestrator.analyze_project(self.p["id"])["profile"]
        orchestrator.discover_failures(self.p["id"], self.profile)
        self.fps = [{**f, "dependencies": db.loads(f["dependencies_json"]), "failure_modes": db.loads(f["failure_modes_json"])}
                    for f in db.get_many("failure_points", "project_id = ?", (self.p["id"],))]

    def generate(self, **override):
        return orchestrator.generate_and_gate_experiments(self.p["id"], {**self.profile, **override}, self.fps)

    def test_supported_project_gets_ready_experiments(self):
        self.assertTrue(any(e["status"] == "READY" for e in self.generate()))

    def test_partially_supported_project_gets_none_and_is_told_why(self):
        exps = self.generate(execution_status="PARTIALLY_SUPPORTED",
                             execution_status_reason="node_modules is not present")
        self.assertTrue(exps)
        for e in exps:
            self.assertEqual(e["status"], "BLOCKED")
            self.assertIn("node_modules is not present", e["block_reason"])
            self.assertIn("Re-analyze", e["block_reason"])
        rows = db.get_many("experiments", "project_id = ?", (self.p["id"],))
        self.assertEqual({r["status"] for r in rows}, {"BLOCKED"})

    def test_reanalyzing_after_a_fix_unblocks_them(self):
        self.generate(execution_status="PARTIALLY_SUPPORTED", execution_status_reason="x")
        again = self.generate()                      # what Re-analyze does once the cause is fixed
        self.assertTrue(any(e["status"] == "READY" for e in again))
        self.assertEqual(len(db.get_many("experiments", "project_id = ?", (self.p["id"],))), len(again))

    def test_profile_from_analysis_row_carries_the_reason(self):
        row = db.get_many("project_analysis", "project_id = ?", (self.p["id"],))[0]
        self.assertIn("execution_status_reason", api._profile_from_analysis_row(row))


if __name__ == "__main__":
    unittest.main()
