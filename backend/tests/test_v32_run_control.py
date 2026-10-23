"""V32: bounded run concurrency, one active run per experiment, CLI gating,
and honest reasoning when a service can't start because of sandbox limits."""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, detection, orchestrator
from app.config import MAX_CONCURRENT_RUNS


def _make_project(tmp):
    z = os.path.join(tmp, "p.zip")
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("app.py", "print('hi')\n")
    db.init_db()
    return orchestrator.create_project(z, "v32-test")


def _insert_experiment(project_id, fault="slow_response"):
    exp_id = db.new_id()
    db.insert("experiments", {
        "id": exp_id, "project_id": project_id, "failure_point_id": None, "name": f"exp-{fault}",
        "category": "network", "target": "http_api", "fault_type": fault, "parameters_json": db.dumps({}),
        "risk_level": 1, "expected_behavior": "x", "safety_requirements_json": db.dumps([]),
        "status": "READY", "block_reason": None, "created_at": db.now(),
    })
    return exp_id


class RunControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project = _make_project(self.tmp)
        self._orig = orchestrator.run_experiment

    def tearDown(self):
        orchestrator.run_experiment = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_same_experiment_cannot_be_started_twice_while_active(self):
        release = threading.Event()

        def slow(experiment_id, run_id=None):
            release.wait(5)
            db.update("experiment_runs", run_id, {"status": "COMPLETED", "finished_at": db.now()})
        orchestrator.run_experiment = slow
        exp = _insert_experiment(self.project["id"])
        first = orchestrator.start_experiment_async(exp)
        with self.assertRaises(orchestrator.ExperimentAlreadyRunning) as cm:
            orchestrator.start_experiment_async(exp)
        self.assertEqual(cm.exception.run_id, first)
        release.set()
        for _ in range(50):  # lock is released once the worker finishes
            try:
                orchestrator.start_experiment_async(exp)
                break
            except orchestrator.ExperimentAlreadyRunning:
                time.sleep(0.1)
        else:
            self.fail("experiment stayed locked after its run finished")

    def test_lock_is_released_when_run_raises(self):
        def boom(experiment_id, run_id=None):
            raise RuntimeError("infra failure")
        orchestrator.run_experiment = boom
        exp = _insert_experiment(self.project["id"])
        run_id = orchestrator.start_experiment_async(exp)
        for _ in range(50):
            if db.get_one("experiment_runs", run_id)["status"] == "FAILED":
                break
            time.sleep(0.1)
        self.assertEqual(db.get_one("experiment_runs", run_id)["status"], "FAILED")
        time.sleep(0.2)
        orchestrator.start_experiment_async(exp)  # must not raise ExperimentAlreadyRunning

    def test_concurrent_runs_never_exceed_the_cap(self):
        lock = threading.Lock()
        state = {"now": 0, "max": 0}

        def tracked(experiment_id, run_id=None):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.25)
            with lock:
                state["now"] -= 1
            db.update("experiment_runs", run_id, {"status": "COMPLETED", "finished_at": db.now()})
        orchestrator.run_experiment = tracked
        run_ids = [orchestrator.start_experiment_async(_insert_experiment(self.project["id"], f"f{i}"))
                   for i in range(MAX_CONCURRENT_RUNS + 4)]
        for _ in range(100):
            if all(db.get_one("experiment_runs", r)["status"] == "COMPLETED" for r in run_ids):
                break
            time.sleep(0.1)
        self.assertTrue(all(db.get_one("experiment_runs", r)["status"] == "COMPLETED" for r in run_ids))
        self.assertLessEqual(state["max"], MAX_CONCURRENT_RUNS)
        self.assertGreater(state["max"], 1)  # still runs in parallel up to the cap

    def test_run_cancelled_while_queued_ends_cancelled_not_stuck(self):
        gate = threading.Event()

        def blocker(experiment_id, run_id=None):
            gate.wait(5)
            db.update("experiment_runs", run_id, {"status": "COMPLETED", "finished_at": db.now()})
        orchestrator.run_experiment = blocker
        blockers = [orchestrator.start_experiment_async(_insert_experiment(self.project["id"], f"b{i}"))
                    for i in range(MAX_CONCURRENT_RUNS)]
        time.sleep(0.3)  # all slots taken
        queued = orchestrator.start_experiment_async(_insert_experiment(self.project["id"], "queued"))
        orchestrator.request_cancel(queued)
        db.update("experiment_runs", queued, {"status": "CANCEL_REQUESTED"})
        gate.set()
        for _ in range(100):
            if db.get_one("experiment_runs", queued)["status"] == "CANCELLED":
                break
            time.sleep(0.1)
        self.assertEqual(db.get_one("experiment_runs", queued)["status"], "CANCELLED")


class ActiveHandleRegistryTests(unittest.TestCase):
    class UnhashableHandle:
        def __init__(self):
            self.killed = False

        def __eq__(self, other):
            return self is other

        def kill(self):
            self.killed = True

    def test_unhashable_handle_can_be_registered_removed_and_cancelled(self):
        run_id = "unhashable-handle-regression"
        handle = self.UnhashableHandle()
        try:
            orchestrator.register_active_handle(run_id, handle)
            orchestrator.register_active_handle(run_id, handle)
            self.assertEqual(orchestrator._active_handles[run_id], [handle])

            orchestrator.unregister_active_handle(run_id, handle)
            self.assertNotIn(run_id, orchestrator._active_handles)

            orchestrator.register_active_handle(run_id, handle)
            orchestrator.cancel_active_handles(run_id)
            self.assertTrue(handle.killed)
            self.assertNotIn(run_id, orchestrator._active_handles)
        finally:
            orchestrator._active_handles.pop(run_id, None)


class CliGatingTests(unittest.TestCase):
    def _exp(self, fault):
        return {"fault_type": fault}

    def test_process_kill_blocked_for_one_shot_cli(self):
        profile = {"adapter": "python_generic_cli", "components": {"http_endpoints": [], "detected_port": None}}
        for fault in ("process_kill", "process_kill_recovery"):
            d = orchestrator._service_requirement(self._exp(fault), profile)
            self.assertFalse(d.allowed)
            self.assertIn("command-line", d.reason)

    def test_file_faults_still_allowed_for_cli(self):
        profile = {"adapter": "python_generic_cli", "components": {"http_endpoints": [], "detected_port": None}}
        for fault in ("missing_file", "permission_denied", "missing_env_var"):
            self.assertTrue(orchestrator._service_requirement(self._exp(fault), profile).allowed)

    def test_services_are_not_blocked(self):
        http = {"adapter": "python_generic_http", "components": {"http_endpoints": [{"method": "GET", "path": "/"}]}}
        cli_with_routes = {"adapter": "java_cli", "components": {"http_endpoints": [{"method": "GET", "path": "/x"}]}}
        cli_with_port = {"adapter": "java_cli", "components": {"http_endpoints": [], "detected_port": 8080}}
        for p in (http, cli_with_routes, cli_with_port):
            self.assertTrue(orchestrator._service_requirement(self._exp("process_kill"), p).allowed, p)


class UnreachableReasoningTests(unittest.TestCase):
    def test_thread_limit_startup_failure_is_explained(self):
        result = {"service_ready": False, "stderr": "Assertion failed: (0) == (uv_thread_create(t.get(), start_thread, this))"}
        out = detection.classify("boundary_input", result)
        self.assertEqual(out["outcome"], "TARGET_UNREACHABLE")
        self.assertIn("process/thread limit", out["reasoning"])

    def test_plain_unreachable_keeps_original_reasoning(self):
        out = detection.classify("boundary_input", {"service_ready": False, "stderr": "ImportError: no module named x"})
        self.assertEqual(out["outcome"], "TARGET_UNREACHABLE")
        self.assertNotIn("thread limit", out["reasoning"])


if __name__ == "__main__":
    unittest.main()
