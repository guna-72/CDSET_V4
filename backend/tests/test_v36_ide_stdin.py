import os
import sys
import tempfile
import unittest

from app import sandbox


class IdeStdinTests(unittest.TestCase):
    def _run(self, code, stdin):
        ws = sandbox.make_workspace(self.src, "ide-run")
        try:
            return sandbox.run_in_sandbox([sys.executable, "avg.py"], ws, timeout=20, stdin_data=stdin)
        finally:
            sandbox.destroy_workspace(ws)

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.src = self.td.name
        with open(os.path.join(self.src, "avg.py"), "w") as f:
            f.write('a=float(input("a "))\nb=float(input("b "))\nprint("avg", (a+b)/2)\n')

    def tearDown(self):
        self.td.cleanup()

    def test_input_is_supplied(self):
        r = self._run(None, "10\n20\n")
        self.assertEqual(r.exit_code, 0, r.stderr)
        self.assertIn("avg 15.0", r.stdout)

    def test_without_input_gives_eoferror(self):
        r = self._run(None, None)
        self.assertNotEqual(r.exit_code, 0)
        self.assertIn("EOFError", r.stderr)


if __name__ == "__main__":
    unittest.main()
