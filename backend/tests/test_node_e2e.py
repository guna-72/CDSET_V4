"""
Proves the Node.js adapter works end-to-end against a real, different-
language sample project — not just the Python one. This test caught
three real bugs during development (node_generic missing from the
HTTP-capable adapter list, raw-Node endpoint detection regex too narrow,
and V8 crashing instantly under RLIMIT_AS) that the Python-only test
suite could never have found.
"""
import os
import sys
import shutil
import tempfile
import unittest

_TEST_DB = tempfile.mktemp(suffix=".db")
os.environ["CHAOS_TUTOR_DB_PATH"] = _TEST_DB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, orchestrator, sandbox  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_ZIP = os.path.join(REPO_ROOT, "sample_projects", "mini_node_api.zip")


class TestNodeEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sandbox.network_isolation_available() and not __import__("app.config", fromlist=["ALLOW_DEGRADED_SANDBOX"]).ALLOW_DEGRADED_SANDBOX:
            raise unittest.SkipTest("full E2E requires kernel network isolation; use Linux/WSL2 or explicitly opt into degraded trusted-dev mode")
        db.init_db()
        if not os.path.exists(SAMPLE_ZIP):
            raise unittest.SkipTest(f"sample zip not built at {SAMPLE_ZIP}")
        if shutil.which("node") is None:
            raise unittest.SkipTest("node binary not available on this host")
        cls.project = orchestrator.create_project(SAMPLE_ZIP, "Mini Node API (e2e test)")
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
        for f in (_TEST_DB, _TEST_DB + "-wal", _TEST_DB + "-shm"):
            if os.path.exists(f):
                os.remove(f)
        shutil.rmtree(cls.project["storage_path"], ignore_errors=True)

    def test_node_project_detected_as_supported(self):
        self.assertEqual(self.analysis["profile"]["execution_status"], "SUPPORTED")
        self.assertEqual(self.analysis["profile"]["adapter"], "node_generic")

    def test_real_endpoints_detected_from_raw_http_createServer_routing(self):
        paths = {e["path"] for e in self.analysis["profile"]["components"]["http_endpoints"]}
        self.assertEqual(paths, {"/health", "/items"})

    def test_unhandled_json_parse_throw_crashes_the_node_process(self):
        exp, res = self.results["malformed_request"]
        self.assertEqual(res["outcome"], "CRASHED")

    def test_missing_type_validation_flagged_as_weak_handling(self):
        exp, res = self.results["boundary_input"]
        self.assertEqual(res["outcome"], "WEAK_HANDLING")

    def test_process_kill_recovery_works_for_node_too(self):
        # this specifically exercises the RLIMIT_AS-skip / --max-old-space-size
        # fix — before it, every restart attempt OOM'd instantly
        exp, res = self.results["process_kill_recovery"]
        self.assertEqual(res["outcome"], "RECOVERED")

    def test_clean_negatives_for_node_too(self):
        for fault_type in ("connection_refused", "request_burst", "slow_response", "process_kill"):
            with self.subTest(fault_type=fault_type):
                _, res = self.results[fault_type]
                self.assertEqual(res["outcome"], "PASSED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
