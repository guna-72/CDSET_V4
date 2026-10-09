import unittest
from app.config import _degraded_sandbox_default


class WindowsDefaultTests(unittest.TestCase):
    def test_defaults_to_degraded(self):
        self.assertTrue(_degraded_sandbox_default(None))
        self.assertTrue(_degraded_sandbox_default(""))

    def test_explicit_setting_wins(self):
        self.assertFalse(_degraded_sandbox_default("false"))
        self.assertTrue(_degraded_sandbox_default("true"))


if __name__ == "__main__":
    unittest.main()
