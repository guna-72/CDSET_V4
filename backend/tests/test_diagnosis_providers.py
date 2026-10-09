import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import diagnosis, llm_providers as lp

EXPERIMENT = {"name": "Malformed request body", "category": "http", "target": "http_api",
              "fault_type": "malformed_request", "expected_behavior": "handled 4xx"}
DETECTION_RESULT = {
    "outcome": "APPLICATION_FAILURE", "reasoning": "server returned 500",
    "evidence": {"stderr": "Traceback...\nValueError: bad input", "exit_code": 1,
                 "chaos": {"status": 500}},
}
PROFILE = {"framework": "Generic HTTP (Python stdlib)"}

ALL_KEY_ENV_VARS = list(lp._ENV_VAR_BY_PROVIDER.values()) + list(lp._SINGULAR_ENV_VAR_BY_PROVIDER.values())


def _clean_env():
    cleared = {k: "" for k in ALL_KEY_ENV_VARS}
    cleared["ENABLE_LLM_DIAGNOSIS"] = ""
    return mock.patch.dict(os.environ, cleared, clear=False)


class TestDiagnosisProviderIntegration(unittest.TestCase):
    def test_no_keys_configured_uses_rule_based(self):
        with _clean_env():
            result = diagnosis.diagnose_run(EXPERIMENT, DETECTION_RESULT, PROFILE)
        self.assertEqual(result["method"], "rule_based")

    def test_keys_configured_without_explicit_enable_never_calls_a_provider(self):
        # This is the exact safety property that matters: pasting keys in
        # must never, by itself, spend them. Patch the provider call with
        # a mock that fails the test if it's invoked at all.
        with _clean_env(), mock.patch.dict(os.environ, {"OPENAI_API_KEYS": "o1", "GROQ_API_KEYS": "g1"}):
            with mock.patch.object(lp, "_call_openai", side_effect=AssertionError("must not be called")), \
                 mock.patch.object(lp, "_call_groq", side_effect=AssertionError("must not be called")):
                result = diagnosis.diagnose_run(EXPERIMENT, DETECTION_RESULT, PROFILE)
        self.assertEqual(result["method"], "rule_based")

    def test_keys_configured_but_all_calls_fail_falls_back_to_rule_based_silently(self):
        # The person looking at a tutor explanation must never see
        # provider/network plumbing — the fallback has to be clean, not
        # just present.
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "g1", "ENABLE_LLM_DIAGNOSIS": "true"}):
            with mock.patch.object(lp, "_call_groq", side_effect=ConnectionError("no network")):
                result = diagnosis.diagnose_run(EXPERIMENT, DETECTION_RESULT, PROFILE)
        self.assertEqual(result["method"], "rule_based")
        evidence_text = " ".join(result["evidence"]).lower()
        for leaky_term in ("llm", "provider", "connectionerror", "fallback", "api key", "groq"):
            self.assertNotIn(leaky_term, evidence_text,
                              f"user-facing evidence must not leak internal LLM plumbing ('{leaky_term}' found)")

    def test_successful_llm_call_is_used_directly(self):
        fake_response = {
            "failure": "llm-generated failure text", "root_cause": "llm root cause",
            "affected_component": "http_api", "impact": "llm impact", "evidence": ["llm evidence"],
            "recommended_fix": "llm fix", "resilience_pattern": "input validation", "confidence": 0.95,
        }
        with _clean_env(), mock.patch.dict(os.environ, {"OPENAI_API_KEYS": "o1", "ENABLE_LLM_DIAGNOSIS": "true"}):
            with mock.patch.object(lp, "_call_openai", return_value=fake_response):
                result = diagnosis.diagnose_run(EXPERIMENT, DETECTION_RESULT, PROFILE)
        self.assertEqual(result["method"], "llm")
        self.assertEqual(result["failure"], "llm-generated failure text")
        self.assertEqual(result["confidence"], 0.95)

    def test_rule_based_diagnosis_still_works_standalone(self):
        # sanity check the fallback path itself is unaffected by this change
        result = diagnosis._rule_based_diagnose(EXPERIMENT, DETECTION_RESULT, PROFILE)
        self.assertEqual(result["method"], "rule_based")
        self.assertIn("ValueError", result["root_cause"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
