import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import detection


class TestDetection(unittest.TestCase):
    def test_handled_4xx_passes(self):
        result = {"service_ready": True, "service_alive_after_fault": True,
                  "chaos": {"ok": True, "status": 400}}
        out = detection.classify("malformed_request", result)
        self.assertEqual(out["outcome"], "PASSED")

    def test_5xx_is_application_failure(self):
        result = {"service_ready": True, "service_alive_after_fault": True,
                  "chaos": {"ok": True, "status": 500}}
        out = detection.classify("malformed_request", result)
        self.assertEqual(out["outcome"], "APPLICATION_FAILURE")

    def test_2xx_on_bad_input_is_weak_handling(self):
        result = {"service_ready": True, "service_alive_after_fault": True,
                  "chaos": {"ok": True, "status": 201}}
        out = detection.classify("boundary_input", result)
        self.assertEqual(out["outcome"], "WEAK_HANDLING")

    def test_process_died_is_crashed(self):
        result = {"service_ready": True, "service_alive_after_fault": False, "chaos": {"ok": False}}
        out = detection.classify("malformed_request", result)
        self.assertEqual(out["outcome"], "CRASHED")

    def test_unreachable_target_is_distinct_from_passed(self):
        result = {"service_ready": False}
        out = detection.classify("connection_refused", result)
        self.assertEqual(out["outcome"], "TARGET_UNREACHABLE")
        self.assertNotEqual(out["outcome"], "PASSED",
                             "spec section 26: NOT_TESTED must never be treated as PASSED")

    def test_startup_crash_with_traceback_is_application_failure(self):
        result = {"service_ready": False, "stderr": "Traceback (most recent call last):\nFileNotFoundError: x"}
        out = detection.classify("missing_file", result)
        self.assertEqual(out["outcome"], "APPLICATION_FAILURE")

    def test_startup_crash_without_traceback_is_passed(self):
        result = {"service_ready": False, "stderr": "config error: MISSING_VAR is required\n"}
        out = detection.classify("missing_env_var", result)
        self.assertEqual(out["outcome"], "PASSED")

    def test_clean_connection_refusal_passes(self):
        result = {"chaos": {"ok": False, "error": "URLError: [Errno 111] Connection refused"}}
        out = detection.classify("connection_refused", result)
        self.assertEqual(out["outcome"], "PASSED")

    def test_process_kill_clean_death_passes(self):
        result = {"process_alive_after_kill": False, "chaos": {"ok": False, "error": "refused"}}
        out = detection.classify("process_kill", result)
        self.assertEqual(out["outcome"], "PASSED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
