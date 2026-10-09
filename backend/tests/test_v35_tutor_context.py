"""V35: the AI Tutor gets the project's real code, the injected error and a working fix.

Covers: locating the right source lines (ignoring docstrings/comments), the rule-based
fixes for Python and Node, the "handled correctly -> tutor not needed" state, the
/tutor-context and /latest-run endpoints (fresh runs are picked up, not just the first),
and — where the sandbox is available — that applying the suggested fix to the real
sample project makes the same experiment PASS.
"""
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["CHAOS_TUTOR_DB_PATH"] = _TEST_DB
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import api, db, orchestrator, sandbox, tutor, tutor_context as tc  # noqa: E402
from app.config import ALLOW_DEGRADED_SANDBOX  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_ZIP = ROOT / "sample_projects" / "mini_task_api.zip"
JS_ZIP = ROOT / "sample_projects" / "mini_node_api.zip"


class Req:
    def __init__(self, **params):
        self.params, self.query, self.user_uid, self.actor = params, {}, "local", "api-token"


class LocatorTests(unittest.TestCase):
    def test_docstring_and_comment_mentions_are_not_code(self):
        src = '"""Parses with json.loads() here."""\n# json.loads(x)\nx = 1\ny = json.loads(raw)\n'
        masked = tc._mask_non_code("python", src)
        hits = [i + 1 for i, l in enumerate(masked) if "json.loads" in l]
        self.assertEqual(hits, [4])

    def test_js_comments_are_masked(self):
        src = "// JSON.parse(a)\n/* JSON.parse(b)\n JSON.parse(c) */\nconst d = JSON.parse(e);\n"
        masked = tc._mask_non_code("javascript", src)
        self.assertEqual([i + 1 for i, l in enumerate(masked) if "JSON.parse" in l], [4])

    def test_js_const_stays_visible_after_try_wrap(self):
        lines = ["    const data = JSON.parse(body);"]
        out = tc._wrap_try("javascript", lines, 0, 0, "", ["      return;"])
        self.assertEqual(out[0].strip(), "let data;")
        self.assertIn("data = JSON.parse(body);", out[2])

    def test_statement_end_covers_python_with_block(self):
        lines = ["with open(P) as f:", "    X = json.load(f)", "", "Y = 1"]
        self.assertEqual(tc._statement_end(lines, 0, "python"), 1)

    def test_field_guards_use_the_fields_the_code_reads(self):
        fields = tc._used_fields("data", ['title = data["title"]', 'n = data.get("count")'], "python")
        self.assertEqual(fields, [("title", True), ("count", False)])


class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.project = orchestrator.create_project(str(PY_ZIP), "Task API (ctx test)")
        cls.other = orchestrator.create_project(str(JS_ZIP), "Node API (ctx test)")

    @classmethod
    def tearDownClass(cls):
        for f in (_TEST_DB, _TEST_DB + "-wal", _TEST_DB + "-shm"):
            if os.path.exists(f):
                os.remove(f)
        for p in (cls.project, cls.other):
            shutil.rmtree(p["storage_path"], ignore_errors=True)

    def _run(self, project, fault, outcome, params=None, status="COMPLETED", started=None):
        exp_id, run_id = db.new_id(), db.new_id()
        db.insert("experiments", {
            "id": exp_id, "project_id": project["id"], "failure_point_id": None,
            "name": f"exp-{fault}", "category": "http", "target": "http_api", "fault_type": fault,
            "parameters_json": db.dumps(params or {"candidate_paths": ["/tasks"]}), "risk_level": 1,
            "expected_behavior": "x", "safety_requirements_json": db.dumps([]),
            "status": "READY", "block_reason": None, "created_at": db.now()})
        db.insert("experiment_runs", {
            "id": run_id, "experiment_id": exp_id, "project_id": project["id"], "status": status,
            "started_at": started or db.now(), "finished_at": db.now(), "outcome": outcome})
        return db.get_one("experiment_runs", run_id)

    def test_failed_run_returns_project_error_code_and_fix(self):
        ctx = tc.build_context(self._run(self.project, "malformed_request", "APPLICATION_FAILURE"))
        self.assertTrue(ctx["tutor_needed"])
        self.assertEqual(ctx["project"]["name"], "Task API (ctx test)")
        self.assertIn("not valid JSON", ctx["injected"]["description"])
        self.assertEqual(ctx["code"]["file"], "app.py")
        self.assertIn("json.loads(raw)", ctx["code"]["raw_snippet"])
        self.assertIn("except (ValueError, TypeError)", ctx["fix"]["code"])
        self.assertIn("400", ctx["fix"]["code"])

    def test_handled_correctly_means_tutor_not_needed_and_no_fix(self):
        ctx = tc.build_context(self._run(self.project, "malformed_request", "PASSED"))
        self.assertFalse(ctx["tutor_needed"])
        self.assertTrue(ctx["handled_correctly"])
        self.assertIsNone(ctx["fix"])

    def test_unreachable_target_is_neither_problem_nor_success(self):
        ctx = tc.build_context(self._run(self.project, "malformed_request", "TARGET_UNREACHABLE"))
        self.assertFalse(ctx["tutor_needed"])
        self.assertFalse(ctx["handled_correctly"])

    def test_node_project_gets_a_javascript_fix(self):
        ctx = tc.build_context(self._run(self.other, "malformed_request", "CRASHED"))
        self.assertEqual(ctx["code"]["file"], "app.js")
        self.assertIn("catch (err)", ctx["fix"]["code"])

    def test_missing_file_fix_is_a_clear_startup_error(self):
        ctx = tc.build_context(self._run(self.project, "missing_file", "APPLICATION_FAILURE",
                                         {"relative_path": "data/seed.json"}))
        self.assertIn("open(SEED_PATH)", ctx["code"]["raw_snippet"])
        self.assertIn("FileNotFoundError", ctx["fix"]["code"])
        self.assertIn("sys.exit(1)", ctx["fix"]["code"])

    def test_running_run_has_no_verdict_yet(self):
        ctx = tc.build_context(self._run(self.project, "malformed_request", None, status="RUNNING"))
        self.assertFalse(ctx["tutor_needed"])
        self.assertFalse(ctx["handled_correctly"])

    def test_endpoint_and_ask_use_the_same_project_code(self):
        run = self._run(self.project, "malformed_request", "APPLICATION_FAILURE")
        code, body = api.get_tutor_context(Req(id=run["id"]))
        self.assertEqual(code, 200)
        self.assertTrue(body["tutor_needed"])
        summary = tc.summarize_for_prompt(body)
        answer = tutor.answer_question("How do I fix this code?", run, None, "", code_context=summary)["answer"]
        self.assertIn("app.py", answer)
        self.assertIn("json.loads(raw)", answer)

    def test_ask_reports_a_pass_instead_of_inventing_a_bug(self):
        run = self._run(self.project, "malformed_request", "PASSED")
        summary = tc.summarize_for_prompt(tc.build_context(run))
        answer = tutor.answer_question("What went wrong?", run, None, "", code_context=summary)["answer"]
        self.assertIn("handled", answer.lower())
        self.assertIn("Nothing needs fixing", answer)

    def test_latest_run_endpoint_follows_new_runs(self):
        proj = orchestrator.create_project(str(PY_ZIP), "Follow test")
        try:
            first = self._run(proj, "malformed_request", "APPLICATION_FAILURE", started=1000.0)
            _, a = api.get_project_latest_run(Req(id=proj["id"]))
            self.assertEqual(a["latest"]["id"], first["id"])
            second = self._run(proj, "empty_input", "PASSED", started=2000.0)
            _, b = api.get_project_latest_run(Req(id=proj["id"]))
            self.assertEqual(b["latest"]["id"], second["id"])
            self.assertEqual(b["latest_completed"]["id"], second["id"])
            running = self._run(proj, "boundary_input", None, status="RUNNING", started=3000.0)
            _, c = api.get_project_latest_run(Req(id=proj["id"]))
            self.assertEqual(c["latest"]["id"], running["id"])
            self.assertEqual(c["latest_completed"]["id"], second["id"])
            self.assertEqual({r["id"] for r in c["recent"]}, {first["id"], second["id"]})
        finally:
            shutil.rmtree(proj["storage_path"], ignore_errors=True)


@unittest.skipUnless(sandbox.network_isolation_available() or ALLOW_DEGRADED_SANDBOX,
                     "needs the sandbox to run real experiments")
class FixActuallyWorksTests(unittest.TestCase):
    """The strongest check: apply the suggested fix to the imported project, re-run the very same
    experiment in the real sandbox, and require the outcome to become PASSED."""

    def _verify(self, zip_path, fault):
        db.init_db()
        proj = orchestrator.create_project(str(zip_path), f"fix-{fault}")
        try:
            an = orchestrator.analyze_project(proj["id"])
            fps = orchestrator.discover_failures(proj["id"], an["profile"])
            exps = orchestrator.generate_and_gate_experiments(proj["id"], an["profile"], fps)
            exp = next(e for e in exps if e["fault_type"] == fault and e["status"] == "READY")
            run = db.get_one("experiment_runs", orchestrator.run_experiment(exp["id"])["run_id"])
            self.assertIn(run["outcome"], tc.PROBLEM_OUTCOMES)
            ctx = tc.build_context(run)
            fix, code = ctx["fix"], ctx["code"]
            path = pathlib.Path(proj["storage_path"]) / code["file"]
            lines = path.read_text().splitlines()
            new = lines[:code["start_line"] - 1] + fix["code"].split("\n") + lines[code["end_line"]:]
            text = "\n".join(new) + "\n"
            for extra in fix["extras"]:
                if "MAX_BODY_BYTES =" in extra:
                    text = extra + "\n" + text
            path.write_text(text)
            after = db.get_one("experiment_runs", orchestrator.run_experiment(exp["id"])["run_id"])
            self.assertEqual(after["outcome"], "PASSED", f"{fault}: {after['outcome']}")
        finally:
            shutil.rmtree(proj["storage_path"], ignore_errors=True)

    def test_python_malformed_request_fix_passes(self):
        self._verify(PY_ZIP, "malformed_request")

    def test_python_oversized_payload_fix_passes(self):
        self._verify(PY_ZIP, "oversized_payload")

    def test_python_boundary_input_fix_passes(self):
        self._verify(PY_ZIP, "boundary_input")

    def test_python_missing_file_fix_passes(self):
        self._verify(PY_ZIP, "missing_file")

    def test_node_malformed_request_fix_passes(self):
        self._verify(JS_ZIP, "malformed_request")

    def test_node_oversized_payload_fix_passes(self):
        self._verify(JS_ZIP, "oversized_payload")


if __name__ == "__main__":
    unittest.main()
