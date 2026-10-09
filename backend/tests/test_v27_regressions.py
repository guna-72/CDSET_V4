"""Regression tests for bugs fixed after V26."""
import http.server
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, detection, intake, orchestrator, safety_gate, sandbox
from app.api import _build_ide_commands, router
from app.http_framework import HTTPError, Request


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)


class IntakeRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_wrapper_folder_containing_same_named_package_is_flattened(self):
        # "mysite/mysite/settings.py" (Django layout) used to crash with shutil.Error.
        z = os.path.join(self.tmp, "a.zip")
        _zip(z, [("mysite/manage.py", "x"), ("mysite/mysite/settings.py", "y")])
        dest = os.path.join(self.tmp, "out")
        intake.validate_and_extract(z, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "manage.py")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "mysite", "settings.py")))
        self.assertFalse([n for n in os.listdir(dest) if n.startswith(".chaos_unwrap")])

    def test_dotdot_prefixed_names_are_not_treated_as_traversal(self):
        z = os.path.join(self.tmp, "b.zip")
        _zip(z, [("p/..hidden/a.txt", "x"), ("p/b.txt", "x")])
        intake.validate_and_extract(z, os.path.join(self.tmp, "out"))

    def test_real_traversal_is_still_rejected(self):
        for bad in ("../evil.txt", "a/../../evil.txt", "..\\..\\evil.txt"):
            z = os.path.join(self.tmp, "t.zip")
            _zip(z, [(bad, "x")])
            with self.assertRaises(intake.IntakeError, msg=bad):
                intake.validate_and_extract(z, os.path.join(self.tmp, "o_" + str(abs(hash(bad)))))

    def test_directory_entries_are_not_counted_as_files(self):
        z = os.path.join(self.tmp, "c.zip")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr(zipfile.ZipInfo("src/"), "")
            zf.writestr("src/a.py", "x")
            zf.writestr("b.py", "x")
        manifest = intake.validate_and_extract(z, os.path.join(self.tmp, "out"))
        self.assertEqual(manifest["file_count"], 2)

    def test_corrupt_member_is_a_clean_rejection_and_leaves_nothing_behind(self):
        z = os.path.join(self.tmp, "d.zip")
        _zip(z, [("a.py", "x" * 5000), ("b.py", "y" * 5000)])
        with open(z, "rb") as fh:
            raw = bytearray(fh.read())
        raw[60] ^= 0xFF  # corrupt compressed/stored data of the first member
        with open(z, "wb") as fh:
            fh.write(raw)
        dest = os.path.join(self.tmp, "out")
        with self.assertRaises(intake.IntakeError):
            intake.validate_and_extract(z, dest)
        self.assertFalse(os.path.exists(dest))


class HttpFrameworkRegressions(unittest.TestCase):
    def test_header_lookup_is_case_insensitive(self):
        req = Request("GET", "/x", {}, {}, {"authorization": "Bearer t", "x-project-name": "n"}, b"")
        self.assertEqual(req.headers.get("Authorization"), "Bearer t")
        self.assertEqual(req.headers.get("X-Project-Name"), "n")
        self.assertIn("AUTHORIZATION", req.headers)

    def test_non_object_json_body_is_a_400_not_a_500(self):
        for body in (b"[]", b'"text"', b"42"):
            req = Request("POST", "/x", {}, {}, {}, body)
            with self.assertRaises(HTTPError) as ctx:
                req.json()
            self.assertEqual(ctx.exception.status, 400)

    def test_empty_body_is_empty_object(self):
        self.assertEqual(Request("POST", "/x", {}, {}, {}, b"").json(), {})


class ProjectLogTailRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_project_logs_return_the_newest_events_oldest_first(self):
        pid, eid, rid = db.new_id(), db.new_id(), db.new_id()
        db.insert("projects", {"id": pid, "name": "logtail", "storage_path": "/nonexistent",
                               "created_at": db.now()})
        db.insert("experiments", {"id": eid, "project_id": pid, "name": "n", "category": "http",
                                  "target": "http_api", "fault_type": "empty_input", "risk_level": 1,
                                  "created_at": db.now()})
        db.insert("experiment_runs", {"id": rid, "experiment_id": eid, "project_id": pid,
                                      "status": "COMPLETED", "started_at": db.now()})
        for i in range(30):
            db.insert("events", {"id": db.new_id(), "run_id": rid, "ts": 1000.0 + i, "type": "SYSTEM",
                                 "message": f"event-{i}", "data_json": "{}"})
        try:
            handler, params = router.match("GET", f"/projects/{pid}/logs")
            req = Request("GET", f"/projects/{pid}/logs", params, {"limit": ["10"]}, {}, b"")
            req.user_uid, req.actor = "local", "local"
            status, payload = handler(req)
            msgs = [e["message"] for e in payload["events"]]
            self.assertEqual(msgs, [f"event-{i}" for i in range(20, 30)])
            self.assertTrue(all("_rid" not in e for e in payload["events"]))
        finally:
            conn = db.get_conn()
            conn.execute("DELETE FROM events WHERE run_id=?", (rid,))
            conn.execute("DELETE FROM experiment_runs WHERE id=?", (rid,))
            conn.execute("DELETE FROM experiments WHERE id=?", (eid,))
            conn.execute("DELETE FROM projects WHERE id=?", (pid,))
            conn.commit()


class OrchestratorFailureRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_non_cancel_runtime_error_marks_run_failed(self):
        pid, eid = db.new_id(), db.new_id()
        db.insert("projects", {"id": pid, "name": "rt", "storage_path": "/nonexistent", "created_at": db.now()})
        db.insert("project_analysis", {
            "id": db.new_id(), "project_id": pid, "languages_json": "[]", "framework": "Flask",
            "execution_status": "SUPPORTED", "components_json": "{}", "structure_json": "{}",
            "entrypoint_json": db.dumps({"entrypoint": "app.py", "adapter": "python_flask", "reason": None}),
            "status": "COMPLETE", "created_at": db.now()})
        db.insert("experiments", {"id": eid, "project_id": pid, "name": "n", "category": "http",
                                  "target": "http_api", "fault_type": "empty_input", "risk_level": 1,
                                  "parameters_json": "{}", "status": "READY", "created_at": db.now()})
        original = orchestrator.chaos_engine.execute_experiment

        def boom(*a, **k):
            raise RuntimeError("engine exploded")
        orchestrator.chaos_engine.execute_experiment = boom
        run_id = db.new_id()
        try:
            with self.assertRaises(RuntimeError):
                orchestrator.run_experiment(eid, run_id=run_id)
            run = db.get_one("experiment_runs", run_id)
            self.assertEqual(run["status"], "FAILED")
            self.assertIn("engine exploded", run["error"])
        finally:
            orchestrator.chaos_engine.execute_experiment = original
            conn = db.get_conn()
            conn.execute("DELETE FROM events WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM experiment_runs WHERE id=?", (run_id,))
            conn.execute("DELETE FROM experiments WHERE id=?", (eid,))
            conn.execute("DELETE FROM project_analysis WHERE project_id=?", (pid,))
            conn.execute("DELETE FROM projects WHERE id=?", (pid,))
            conn.commit()


class DetectionReadinessRegression(unittest.TestCase):
    def test_service_that_never_started_is_unreachable_not_passed(self):
        for fault in ("connection_refused", "process_kill", "process_kill_recovery", "db_connection_refused"):
            result = {"service_ready": False, "chaos": {"ok": False, "error": "Connection refused"},
                      "process_alive_after_kill": False}
            self.assertEqual(detection.classify(fault, result)["outcome"], "TARGET_UNREACHABLE", fault)

    def test_missing_env_var_that_boots_fine_is_passed_with_fallback_reasoning(self):
        out = detection.classify("missing_env_var", {"service_ready": True, "stderr": "Traceback (most recent call last)"})
        self.assertEqual(out["outcome"], "PASSED")
        self.assertIn("fallback", out["reasoning"])


@unittest.skipUnless(sandbox.network_isolation_available() or sandbox.ALLOW_DEGRADED_SANDBOX,
                     "needs kernel network isolation (or degraded mode)")
class ChaosEngineReadinessRegression(unittest.TestCase):
    def test_connection_refused_reports_service_ready_false_for_a_crashing_target(self):
        from app import chaos_engine
        with tempfile.TemporaryDirectory() as td:
            pathlib.Path(td, "app.py").write_text("import sys\nsys.exit(3)\n")
            profile = {"adapter": "python_generic_http", "entrypoint": "app.py", "components": {"env_vars": []}}
            exp = {"parameters": {"candidate_paths": ["/"]}}
            result = chaos_engine._fault_connection_refused(exp, td, profile)
            self.assertIs(result["service_ready"], False)
            self.assertEqual(detection.classify("connection_refused", result)["outcome"], "TARGET_UNREACHABLE")


class SandboxRegressions(unittest.TestCase):
    def test_home_is_preserved_but_toolchain_caches_go_to_the_workspace(self):
        env = sandbox._build_env(None, "/some/workspace")
        self.assertEqual(env["HOME"], os.environ.get("HOME", "/some/workspace"))
        for key in ("XDG_CACHE_HOME", "GOCACHE", "npm_config_cache"):
            self.assertTrue(env[key].startswith("/some/workspace/"), key)
        env = sandbox._build_env({"GOCACHE": "/custom"}, "/some/workspace")
        self.assertEqual(env["GOCACHE"], "/custom")

    @unittest.skipUnless(os.name == "posix", "POSIX launcher shim")
    def test_home_dependent_python_launcher_still_starts_in_the_sandbox(self):
        # pyenv/asdf-style: `python3` on PATH is a shim that finds the real
        # interpreter through $HOME. Rewriting HOME broke every sandboxed python.
        import subprocess
        base = tempfile.mkdtemp()
        try:
            os.chmod(base, 0o755)
            home = os.path.join(base, "home", ".realpy")
            os.makedirs(home)
            os.symlink(os.path.realpath(shutil.which("python3")), os.path.join(home, "python3"))
            shimdir = os.path.join(base, "shim")
            os.makedirs(shimdir)
            shim = os.path.join(shimdir, "python3")
            with open(shim, "w") as fh:
                fh.write('#!/bin/sh\nexec "$HOME/.realpy/python3" "$@"\n')
            os.chmod(shim, 0o755)
            for root, dirs, _files in os.walk(base):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o755)
            src = tempfile.mkdtemp()
            os.chmod(src, 0o755)
            ws = sandbox.make_workspace(src, "homeshim")
            old_env = {k: os.environ.get(k) for k in ("PATH", "HOME")}
            os.environ["PATH"] = shimdir + os.pathsep + os.environ["PATH"]
            os.environ["HOME"] = os.path.join(base, "home")
            try:
                res = sandbox.run_in_sandbox(["python3", "-c", "print('alive')"], cwd=ws)
            finally:
                for k, v in old_env.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                sandbox.destroy_workspace(ws)
                shutil.rmtree(src, ignore_errors=True)
            self.assertEqual(res.exit_code, 0, res.stderr)
            self.assertIn("alive", res.stdout)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_direct_probe_does_not_follow_redirects_off_loopback(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/steal")
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            res = sandbox.probe_http_direct(srv.server_address[1], "/", "GET", None, None, 2)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], 302)

    def test_direct_probe_accepts_path_without_leading_slash(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            res = sandbox.probe_http_direct(srv.server_address[1], "tasks", "GET", None, None, 2)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], 200)


class RouteDiscoveryRegressions(unittest.TestCase):
    def test_flask_route_methods_keyword_is_read(self):
        from app import analyzer
        with tempfile.TemporaryDirectory() as td:
            pathlib.Path(td, "app.py").write_text(
                "from flask import Flask\napp = Flask(__name__)\n"
                "@app.route('/items', methods=['POST', 'get'])\ndef items():\n    return 'x'\n"
                "@app.route('/plain')\ndef plain():\n    return 'x'\n")
            comps = analyzer._detect_components(td, ["app.py"], ["app.py"], "Flask")
            eps = {(e["method"], e["path"]) for e in comps["http_endpoints"]}
            self.assertIn(("POST", "/items"), eps)
            self.assertIn(("GET", "/items"), eps)
            self.assertIn(("ROUTE", "/plain"), eps)

    def test_generated_experiments_use_concrete_paths_for_route_params(self):
        from app.experiment_generator import generate_experiments
        profile = {"components": {"http_endpoints": [
            {"method": "POST", "path": "/tasks/<int:task_id>/done"},
            {"method": "GET", "path": "/users/:id"}]}}
        fps = [{"component": "http_api", "type": "network_interface"}]
        exps = generate_experiments(profile, fps)
        malformed = next(e for e in exps if e["fault_type"] == "malformed_request")
        self.assertEqual(malformed["parameters"]["candidate_paths"][0], "/tasks/1/done")
        for e in exps:
            for p in e["parameters"].get("candidate_paths", []):
                self.assertNotRegex(p, r"[<>:{}]")


class MiscRegressions(unittest.TestCase):
    def test_compiled_ide_binaries_are_launched_with_an_explicit_relative_path(self):
        for adapter in ("c_cli", "cpp_cli", "rust_cli"):
            _, run = _build_ide_commands(adapter, "main.c", pathlib.Path("main.c"), "/tmp")
            self.assertTrue(run[0].startswith("./"), adapter)

    def test_safety_gate_catches_windows_style_storage_paths(self):
        exp = {"name": "n", "category": "filesystem", "target": "file:x", "fault_type": "missing_file",
               "parameters": {"relative_path": "C:\\app\\data\\storage\\abc\\x"}, "risk_level": 1,
               "expected_behavior": "e", "safety_requirements": []}
        decision = safety_gate.evaluate(exp, {"file:x"})
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
