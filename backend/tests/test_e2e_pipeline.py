"""
End-to-end pipeline test (spec section 50's "Definition of Done").

Runs the ACTUAL pipeline — real intake, real analysis, real sandboxed
subprocess execution, real HTTP traffic, real detection, real rule-based
diagnosis — against the real sample project. No mocking of the chaos
engine or sandbox: this is the test that proves Rule 4 ("no fake
functionality") end to end.

Uses an isolated, disposable SQLite DB (set via CHAOS_TUTOR_DB_PATH
before app.config/app.db are imported) so it never touches the DB used
for interactive demos in this session.
"""
import os
import sys
import shutil
import tempfile
import unittest

_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["CHAOS_TUTOR_DB_PATH"] = _TEST_DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, orchestrator, sandbox  # noqa: E402  (must come after env var is set)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_ZIP = os.path.join(REPO_ROOT, "sample_projects", "mini_task_api.zip")


class TestEndToEndPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sandbox.network_isolation_available() and not __import__("app.config", fromlist=["ALLOW_DEGRADED_SANDBOX"]).ALLOW_DEGRADED_SANDBOX:
            raise unittest.SkipTest("full E2E requires kernel network isolation; use Linux/WSL2 or explicitly opt into degraded trusted-dev mode")
        db.init_db()
        if not os.path.exists(SAMPLE_ZIP):
            raise unittest.SkipTest(f"sample zip not built at {SAMPLE_ZIP}")
        cls.project = orchestrator.create_project(SAMPLE_ZIP, "Mini Task API (e2e test)")
        cls.analysis = orchestrator.analyze_project(cls.project["id"])
        cls.failure_points = orchestrator.discover_failures(cls.project["id"], cls.analysis["profile"])
        cls.experiments = orchestrator.generate_and_gate_experiments(
            cls.project["id"], cls.analysis["profile"], cls.failure_points
        )
        cls.results = {}
        for exp in cls.experiments:
            if exp["status"] != "READY":
                continue
            res = orchestrator.run_experiment(exp["id"])
            cls.results[exp["fault_type"]] = (exp, res)

    @classmethod
    def tearDownClass(cls):
        # SQLite connections are thread-local and remain open on the test
        # runner thread. Windows refuses to delete an open database file.
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            del db._local.conn
        for f in (_TEST_DB, _TEST_DB + "-wal", _TEST_DB + "-shm"):
            if os.path.exists(f):
                os.remove(f)
        shutil.rmtree(cls.project["storage_path"], ignore_errors=True)

    # ---- pipeline structure ----

    def test_upload_validated_and_isolated(self):
        self.assertTrue(os.path.isdir(self.project["storage_path"]))
        self.assertEqual(self.project["status"], "UPLOADED")

    def test_original_upload_still_intact_after_all_runs(self):
        # The whole point of ANALYSIS/EXPERIMENT copies: original is never touched.
        with open(os.path.join(self.project["storage_path"], "app.py")) as f:
            content = f.read()
        self.assertIn("BUG #1", content)
        self.assertIn("BUG #2", content)

    def test_project_correctly_analyzed_as_supported(self):
        profile = self.analysis["profile"]
        self.assertEqual(profile["execution_status"], "SUPPORTED")
        self.assertEqual(profile["adapter"], "python_generic_http")

    def test_project_aware_no_database_experiments_generated(self):
        self.assertFalse(any(e["fault_type"] == "db_connection_refused" for e in self.experiments),
                          "sample project has no DB signal -> must generate zero DB experiments")

    def test_at_least_eight_experiments_generated(self):
        self.assertGreaterEqual(len(self.experiments), 8)  # spec section 12: ~8-12

    def test_all_generated_experiments_passed_safety_gate(self):
        blocked = [e for e in self.experiments if e["status"] == "BLOCKED"]
        self.assertEqual(blocked, [], f"unexpected blocks: {blocked}")

    # ---- the actual point: real bugs, really found ----

    def test_missing_seed_file_is_detected_as_application_failure(self):
        exp, res = self.results["missing_file"]
        self.assertEqual(res["outcome"], "APPLICATION_FAILURE")
        self.assertIn("FileNotFoundError", res["diagnosis"]["root_cause"])
        self.assertGreaterEqual(res["diagnosis"]["confidence"], 0.8)

    def test_permission_denied_on_seed_file_is_detected(self):
        if os.name == "posix" and hasattr(os, "geteuid") and os.geteuid() == 0:
            # A process running as root bypasses POSIX file permission bits
            # entirely (CAP_DAC_OVERRIDE) - chmod 000 on the sandboxed copy
            # has no effect for it, so the app reads the file fine and the
            # fault is a legitimate no-op here, not a detection bug. This
            # mirrors the setUpClass skip above for other environment
            # prerequisites this suite can't control.
            raise unittest.SkipTest(
                "permission_denied has no effect on a process running as root "
                "(uid 0 bypasses file permission bits) — run as a non-root user "
                "to exercise this experiment"
            )
        exp, res = self.results["permission_denied"]
        self.assertEqual(res["outcome"], "APPLICATION_FAILURE")
        self.assertIn("PermissionError", res["diagnosis"]["root_cause"])

    def test_malformed_json_body_is_detected_as_application_failure(self):
        exp, res = self.results["malformed_request"]
        self.assertEqual(exp["parameters"]["candidate_paths"][0], "/tasks",
                          "must target the real POST endpoint, not a GET-only path")
        self.assertEqual(res["outcome"], "APPLICATION_FAILURE")
        self.assertIn("JSONDecodeError", res["diagnosis"]["root_cause"])

    def test_unvalidated_field_types_flagged_as_weak_handling(self):
        exp, res = self.results["boundary_input"]
        self.assertEqual(res["outcome"], "WEAK_HANDLING")

    # ---- honest negatives: things that should NOT be flagged ----

    def test_stopped_service_reports_clean_refusal_not_a_false_failure(self):
        exp, res = self.results["connection_refused"]
        self.assertEqual(res["outcome"], "PASSED")

    def test_fast_endpoints_do_not_falsely_trigger_slow_response(self):
        exp, res = self.results["slow_response"]
        self.assertEqual(res["outcome"], "PASSED")

    def test_process_kill_is_observed_cleanly(self):
        exp, res = self.results["process_kill"]
        self.assertEqual(res["outcome"], "PASSED")

    # ---- new features added this pass ----

    def test_supervised_restart_recovers_the_service(self):
        exp, res = self.results["process_kill_recovery"]
        self.assertEqual(res["outcome"], "RECOVERED")
        self.assertTrue(res["diagnosis"]["confidence"] >= 0)  # diagnosis produced without error
        self.assertIn("restart", res["diagnosis"]["resilience_pattern"].lower())

    def test_request_burst_handled_without_crashing(self):
        exp, res = self.results["request_burst"]
        self.assertIn(res["outcome"], ("PASSED", "WEAK_HANDLING"))  # never CRASHED/APPLICATION_FAILURE for a static GET

    def test_invalid_content_type_does_not_crash_a_permissive_parser(self):
        exp, res = self.results["invalid_content_type"]
        # the sample app ignores Content-Type entirely and parses the body
        # as JSON regardless, so a well-formed JSON body with the "wrong"
        # header still succeeds — a real, honest negative result
        self.assertIn(res["outcome"], ("PASSED", "WEAK_HANDLING"))

    def test_services_actually_ran_network_isolated(self):
        from app import sandbox
        if not sandbox.network_isolation_available():
            self.skipTest("Windows Firewall isolation unavailable (backend not running elevated)")
        _, res = self.results["malformed_request"]
        self.assertTrue(res["raw_result"].get("service_ready"))
        # can't directly inspect handle here (already torn down), but the
        # dedicated sandbox tests in test_sandbox_security.py assert the
        # isolation property directly against a live handle

    # ---- coverage tracking (spec section 26) ----

    def test_coverage_report_reflects_real_run_state(self):
        report = orchestrator.coverage_report(self.project["id"])
        self.assertGreater(report["total_failure_points"], 0)
        self.assertGreater(report["by_coverage_status"].get("TESTED", 0), 0)
        # nothing should ever be silently counted as passed-by-default
        self.assertNotIn("PASSED", report["by_coverage_status"])

    def test_project_report_reflects_real_findings(self):
        report = orchestrator.project_report(self.project["id"])
        self.assertGreater(report["total_runs"], 0)
        self.assertIsNotNone(report["resilience_score_pct"])
        finding_experiments = {f["experiment"] for f in report["findings"]}
        exp, _ = self.results["missing_file"]
        self.assertIn(exp["name"], finding_experiments)

    def test_project_report_lists_one_accurate_row_per_test_case(self):
        report = orchestrator.project_report(self.project["id"])
        rows = {c["fault_type"]: c for c in report["test_cases"]}
        self.assertEqual(len(rows), len(self.results), "one row per test case that was run")
        self.assertEqual(len(report["test_cases"]), len(rows), "no duplicate rows")
        for fault_type, (_exp, res) in self.results.items():
            self.assertIn(fault_type, rows)
            self.assertEqual(rows[fault_type]["outcome"], res["outcome"],
                             f"report outcome for {fault_type} must match the real run")
            self.assertEqual(rows[fault_type]["status"], "COMPLETED")

    def test_tutor_session_created_for_every_run(self):
        exp, res = self.results["missing_file"]
        self.assertIn("tutor_session_id", res)
        session_rows = db.get_many("tutor_sessions", "run_id = ?", (res["run_id"],))
        self.assertEqual(len(session_rows), 1)
        explanation = db.loads(session_rows[0]["explanation_json"])
        self.assertTrue(explanation["is_problem"])

    def test_tutor_answer_evaluation_works_end_to_end(self):
        exp, res = self.results["missing_file"]
        session_rows = db.get_many("tutor_sessions", "run_id = ?", (res["run_id"],))
        session_id = session_rows[0]["id"]
        result = orchestrator.answer_tutor_question(session_id, "wrap the file read in a try/except block")
        self.assertIn("correct", result)

    def test_list_recent_runs_includes_this_project_and_tutor_session_ids(self):
        recent = orchestrator.list_recent_runs(limit=50)
        run_ids = {r["run_id"] for r in recent}
        _, missing_file_res = self.results["missing_file"]
        self.assertIn(missing_file_res["run_id"], run_ids)
        entry = next(r for r in recent if r["run_id"] == missing_file_res["run_id"])
        self.assertEqual(entry["project_name"], self.project["name"])
        self.assertIsNotNone(entry["tutor_session_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
