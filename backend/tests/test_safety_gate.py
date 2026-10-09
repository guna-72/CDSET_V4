import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import safety_gate


def base_experiment(**overrides):
    exp = {
        "name": "Malformed request body", "category": "http", "target": "http_api",
        "fault_type": "malformed_request", "parameters": {}, "risk_level": 1,
        "expected_behavior": "handled 4xx", "safety_requirements": [],
    }
    exp.update(overrides)
    return exp


class TestSafetyGate(unittest.TestCase):
    def test_valid_experiment_allowed(self):
        decision = safety_gate.evaluate(base_experiment(), {"http_api"})
        self.assertTrue(decision.allowed)

    def test_unknown_target_blocked(self):
        decision = safety_gate.evaluate(base_experiment(target="nonexistent_component"), {"http_api"})
        self.assertFalse(decision.allowed)
        self.assertIn("does not correspond to a discovered failure point", decision.reason)

    def test_forbidden_fault_type_blocked(self):
        decision = safety_gate.evaluate(base_experiment(fault_type="resource_exhaustion"), {"http_api"})
        self.assertFalse(decision.allowed)
        self.assertIn("forbidden", decision.reason)

    def test_unrecognized_fault_type_blocked(self):
        decision = safety_gate.evaluate(base_experiment(fault_type="ai_invented_fault_xyz"), {"http_api"})
        self.assertFalse(decision.allowed)
        self.assertIn("not a recognized library template", decision.reason)

    def test_missing_required_field_blocked(self):
        exp = base_experiment()
        del exp["risk_level"]
        decision = safety_gate.evaluate(exp, {"http_api"})
        self.assertFalse(decision.allowed)
        self.assertIn("schema validation failed", decision.reason)

    def test_out_of_range_risk_level_blocked(self):
        decision = safety_gate.evaluate(base_experiment(risk_level=99), {"http_api"})
        self.assertFalse(decision.allowed)

    def test_external_host_for_connection_refused_blocked(self):
        exp = base_experiment(fault_type="connection_refused", target="http_api",
                               parameters={"host": "evil.example.com"})
        decision = safety_gate.evaluate(exp, {"http_api"})
        self.assertFalse(decision.allowed)
        self.assertIn("localhost", decision.reason)

    def test_reference_to_original_storage_path_blocked(self):
        exp = base_experiment(parameters={"path": "/home/claude/chaos_backend/data/storage/xyz/app.py"})
        decision = safety_gate.evaluate(exp, {"http_api"})
        self.assertFalse(decision.allowed)
        self.assertIn("original upload storage path", decision.reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
