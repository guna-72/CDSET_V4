import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import llm_providers as lp

ALL_KEY_ENV_VARS = list(lp._ENV_VAR_BY_PROVIDER.values()) + list(lp._SINGULAR_ENV_VAR_BY_PROVIDER.values())


def _clean_env():
    """Context manager that clears every provider key env var (and the
    ENABLE_LLM_DIAGNOSIS switch), so tests never depend on (or leak
    into) the real shell environment."""
    cleared = {k: "" for k in ALL_KEY_ENV_VARS}
    cleared["ENABLE_LLM_DIAGNOSIS"] = ""
    return mock.patch.dict(os.environ, cleared, clear=False)


class TestKeyParsing(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(lp._parse_keys("a,b,c"), ["a", "b", "c"])

    def test_newline_separated(self):
        self.assertEqual(lp._parse_keys("a\nb\nc"), ["a", "b", "c"])

    def test_mixed_commas_and_newlines_with_whitespace(self):
        self.assertEqual(lp._parse_keys(" a ,\nb,\n c \n,d"), ["a", "b", "c", "d"])

    def test_empty_entries_dropped(self):
        self.assertEqual(lp._parse_keys("a,,b,\n,c"), ["a", "b", "c"])

    def test_duplicates_dropped_preserving_first_occurrence_order(self):
        self.assertEqual(lp._parse_keys("a,b,a,c,b"), ["a", "b", "c"])

    def test_empty_string_gives_empty_list(self):
        self.assertEqual(lp._parse_keys(""), [])


class TestLoadKeys(unittest.TestCase):
    def test_plural_env_var_parsed_per_provider(self):
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "g1,g2", "OPENAI_API_KEYS": "o1"}):
            keys = lp.load_keys()
            self.assertEqual(keys.get("groq"), ["g1", "g2"])
            self.assertEqual(keys.get("openai"), ["o1"])
            self.assertNotIn("gemini", keys)

    def test_singular_env_var_folded_in(self):
        with _clean_env(), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "solo-key"}):
            keys = lp.load_keys()
            self.assertEqual(keys.get("anthropic"), ["solo-key"])

    def test_singular_and_plural_combined_without_duplication(self):
        with _clean_env(), mock.patch.dict(os.environ, {
            "OPENAI_API_KEYS": "k1,k2", "OPENAI_API_KEY": "k1",  # k1 already present via plural
        }):
            self.assertEqual(lp.load_keys().get("openai"), ["k1", "k2"])

    def test_no_keys_configured(self):
        with _clean_env():
            self.assertEqual(lp.load_keys(), {})
            self.assertFalse(lp.any_keys_configured())


class TestDiagnosisEnabledGate(unittest.TestCase):
    """The safety switch: pasting keys in must never, by itself, start
    spending them. diagnosis_enabled() requires BOTH a configured key
    AND the separate ENABLE_LLM_DIAGNOSIS opt-in."""

    def test_keys_alone_do_not_enable_diagnosis(self):
        with _clean_env(), mock.patch.dict(os.environ, {"OPENAI_API_KEYS": "o1"}):
            self.assertTrue(lp.any_keys_configured())
            self.assertFalse(lp.explicitly_enabled())
            self.assertFalse(lp.diagnosis_enabled())

    def test_flag_alone_without_keys_does_not_enable_diagnosis(self):
        with _clean_env(), mock.patch.dict(os.environ, {"ENABLE_LLM_DIAGNOSIS": "true"}):
            self.assertFalse(lp.any_keys_configured())
            self.assertTrue(lp.explicitly_enabled())
            self.assertFalse(lp.diagnosis_enabled())

    def test_both_keys_and_flag_enables_diagnosis(self):
        with _clean_env(), mock.patch.dict(os.environ, {"OPENAI_API_KEYS": "o1", "ENABLE_LLM_DIAGNOSIS": "true"}):
            self.assertTrue(lp.diagnosis_enabled())

    def test_flag_is_case_insensitive_and_accepts_common_truthy_values(self):
        for value in ("true", "True", "TRUE", "1", "yes", "on"):
            with _clean_env(), mock.patch.dict(os.environ, {"OPENAI_API_KEYS": "o1", "ENABLE_LLM_DIAGNOSIS": value}):
                self.assertTrue(lp.diagnosis_enabled(), f"expected {value!r} to enable diagnosis")

    def test_falsy_or_garbage_flag_values_do_not_enable(self):
        for value in ("false", "0", "no", "off", "", "nonsense"):
            with _clean_env(), mock.patch.dict(os.environ, {"OPENAI_API_KEYS": "o1", "ENABLE_LLM_DIAGNOSIS": value}):
                self.assertFalse(lp.diagnosis_enabled(), f"expected {value!r} to NOT enable diagnosis")


class TestRotation(unittest.TestCase):
    def test_rotation_order_advances_each_call(self):
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "g1,g2", "OPENAI_API_KEYS": "o1"}):
            pool = lp.KeyPool()
            first = pool.rotation_order()
            second = pool.rotation_order()
            third = pool.rotation_order()
            self.assertEqual(len(first), 3)
            # each call should start from a different position
            starts = {first[0], second[0], third[0]}
            self.assertGreaterEqual(len(starts), 2, "rotation must not always start at the same entry")

    def test_rotation_order_wraps_and_contains_every_entry_each_time(self):
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "g1,g2,g3"}):
            pool = lp.KeyPool()
            for _ in range(5):
                order = pool.rotation_order()
                self.assertEqual(set(order), {("groq", "g1"), ("groq", "g2"), ("groq", "g3")})

    def test_empty_pool_returns_empty_order(self):
        with _clean_env():
            self.assertEqual(lp.KeyPool().rotation_order(), [])


class TestFailover(unittest.TestCase):
    def setUp(self):
        # _POOL is a shared, stateful singleton (by design — its rotation
        # index is meant to persist across real calls in production so
        # load spreads across keys). That statefulness must not leak
        # between tests, so each test gets its own fresh pool.
        self._pool_patch = mock.patch.object(lp, "_POOL", lp.KeyPool())
        self._pool_patch.start()

    def tearDown(self):
        self._pool_patch.stop()

    def test_falls_over_to_next_key_on_failure(self):
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "bad1,bad2,good"}):
            calls = []

            def fake_groq(key, model, sp, uc, timeout):
                calls.append(key)
                if key != "good":
                    raise ConnectionError("simulated failure")
                return {"failure": None, "root_cause": None, "confidence": 0.5}

            with mock.patch.object(lp, "_call_groq", side_effect=fake_groq):
                result = lp.diagnose_with_llm("system", "user")
            self.assertEqual(result["confidence"], 0.5)
            self.assertEqual(len(calls), 3)  # tried bad1, bad2, then good

    def test_falls_over_across_providers(self):
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "g1", "OPENAI_API_KEYS": "o1"}):
            with mock.patch.object(lp, "_call_groq", side_effect=ConnectionError("down")), \
                 mock.patch.object(lp, "_call_openai", return_value={"confidence": 0.7}):
                result = lp.diagnose_with_llm("system", "user")
            self.assertEqual(result["confidence"], 0.7)

    def test_all_providers_failing_raises_with_masked_keys_only(self):
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "supersecretkey12345"}):
            with mock.patch.object(lp, "_call_groq", side_effect=ConnectionError("down")):
                with self.assertRaises(lp.AllProvidersFailedError) as ctx:
                    lp.diagnose_with_llm("system", "user")
            message = str(ctx.exception)
            self.assertNotIn("supersecretkey12345", message)
            self.assertIn("groq", message)

    def test_no_keys_configured_raises_immediately(self):
        with _clean_env():
            with self.assertRaises(lp.AllProvidersFailedError):
                lp.diagnose_with_llm("system", "user")

    def test_malformed_json_response_counts_as_failure_and_falls_over(self):
        with _clean_env(), mock.patch.dict(os.environ, {"GROQ_API_KEYS": "g1", "OPENAI_API_KEYS": "o1"}):
            with mock.patch.object(lp, "_call_groq", side_effect=ValueError("bad json")), \
                 mock.patch.object(lp, "_call_openai", return_value={"confidence": 0.4}):
                result = lp.diagnose_with_llm("system", "user")
            self.assertEqual(result["confidence"], 0.4)


class TestProviderDefaults(unittest.TestCase):
    """Locks in the actually-free defaults verified for this pass — see
    the comment above _PROVIDER_ORDER in app/llm_providers.py. Catches a
    real bug that was here before: OpenRouter defaulted to
    'openai/gpt-4o-mini', which is a REAL BILLED call through OpenRouter,
    not a free one."""

    def test_openrouter_defaults_to_the_official_free_router(self):
        self.assertEqual(lp._provider_config("openrouter")["default_model"], "openrouter/free")

    def test_free_tier_providers_are_tried_before_paid_only_ones(self):
        order = lp._PROVIDER_ORDER
        self.assertLess(order.index("groq"), order.index("deepseek"))
        self.assertLess(order.index("gemini"), order.index("deepseek"))
        self.assertLess(order.index("openrouter"), order.index("openai"))


class TestMasking(unittest.TestCase):
    def test_mask_keeps_only_a_few_characters(self):
        masked = lp._mask("sk-ant-abcdefghijklmnop")
        self.assertNotIn("abcdefghijklmnop", masked)
        self.assertTrue(masked.startswith("sk-a"))

    def test_short_key_fully_masked(self):
        self.assertEqual(lp._mask("short"), "***")


if __name__ == "__main__":
    unittest.main(verbosity=2)
