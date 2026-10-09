import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import tutor

EXPERIMENT = {"name": "Malformed request body", "target": "http_api", "fault_type": "malformed_request"}


class TestTutor(unittest.TestCase):
    def test_explain_failure_case(self):
        detection_result = {"outcome": "APPLICATION_FAILURE", "reasoning": "server returned 500",
                             "evidence": {"stderr": "Traceback...\nValueError: bad"}}
        diagnosis = {"failure": "crashed", "root_cause": "unhandled ValueError",
                     "affected_component": "http_api", "evidence": ["x"], "impact": "downtime",
                     "recommended_fix": "add validation", "resilience_pattern": "input validation",
                     "confidence": 0.9}
        explanation = tutor.explain(EXPERIMENT, detection_result, diagnosis)
        self.assertTrue(explanation["is_problem"])
        self.assertEqual(explanation["why"], "unhandled ValueError")
        self.assertEqual(explanation["concept"], "input validation")

    def test_explain_passed_case_has_no_problem_flag(self):
        detection_result = {"outcome": "PASSED", "reasoning": "handled cleanly", "evidence": {}}
        diagnosis = {"failure": None, "root_cause": None, "affected_component": "http_api",
                     "evidence": None, "impact": None, "recommended_fix": None,
                     "resilience_pattern": None, "confidence": 0.6}
        explanation = tutor.explain(EXPERIMENT, detection_result, diagnosis)
        self.assertFalse(explanation["is_problem"])
        self.assertIn("handled cleanly", explanation["what_happened"])

    def test_recovery_note_for_recovered_case(self):
        experiment = {"name": "Recovery after kill", "target": "main_process", "fault_type": "process_kill_recovery"}
        detection_result = {"outcome": "RECOVERED", "reasoning": "recovered",
                             "evidence": {"recovered": True, "restart_events": [{"recovered_after_s": 1.2}]}}
        note = tutor._recovery_note(experiment, detection_result)
        self.assertIn("1.2s", note)

    def test_question_and_answer_evaluation_round_trip(self):
        detection_result = {"outcome": "APPLICATION_FAILURE", "reasoning": "x", "evidence": {}}
        diagnosis = {"resilience_pattern": "input validation"}
        question = tutor.generate_question(EXPERIMENT, detection_result, diagnosis)
        self.assertIn("_concept", question)
        good = tutor.evaluate_answer(question, "you need to validate the input before using it")
        self.assertTrue(good["correct"])
        bad = tutor.evaluate_answer(question, "just restart the server I guess")
        self.assertFalse(bad["correct"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
