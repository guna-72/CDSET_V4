import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import sandbox
from app.config import WORKSPACE_DIR

PYTHON = sys.executable


class TestSandboxSecurity(unittest.TestCase):
    def setUp(self):
        self.src = os.path.join(tempfile.gettempdir(), "sandbox_src_test")
        shutil.rmtree(self.src, ignore_errors=True)
        os.makedirs(self.src)
        with open(os.path.join(self.src, "app.py"), "w") as f:
            f.write("print('hello from sandboxed app')\n")
        self.ws = sandbox.make_workspace(self.src, "sectest")

    def tearDown(self):
        sandbox.destroy_workspace(self.ws)
        shutil.rmtree(self.src, ignore_errors=True)

    def test_original_source_never_modified(self):
        with open(os.path.join(self.src, "app.py")) as f:
            before = f.read()
        sandbox.run_in_sandbox(
            [PYTHON, "-c", "open('app.py','a').write('TAMPERED')"], cwd=self.ws
        )
        with open(os.path.join(self.src, "app.py")) as f:
            after = f.read()
        self.assertEqual(before, after, "original upload must never be modified by a sandbox run")

    def test_network_capability_fails_closed_without_degraded_opt_in(self):
        from app import sandbox
        from app.config import ALLOW_DEGRADED_SANDBOX
        if sandbox.network_isolation_available():
            self.skipTest("host has Windows Firewall isolation available (running elevated); "
                           "fail-closed fallback is not exercised")
        if ALLOW_DEGRADED_SANDBOX:
            self.skipTest("degraded sandbox explicitly enabled by environment")
        with self.assertRaises(sandbox.SandboxError):
            sandbox.require_network_isolation()

    def test_wall_clock_timeout_kills_process(self):
        result = sandbox.run_in_sandbox(
            [PYTHON, "-c", "import time; time.sleep(30)"], cwd=self.ws, timeout=2
        )
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertLess(result.duration_seconds, 12)

    def test_argv_must_be_a_list_not_a_shell_string(self):
        with self.assertRaises(sandbox.SandboxError):
            sandbox.run_in_sandbox(f"{PYTHON} -c 'print(1)'", cwd=self.ws)  # a string, not a list

    def test_command_injection_payload_is_inert(self):
        # A classic injection payload passed as a single argv element must
        # be treated as literal text, never interpreted by a shell.
        payload = "; rm -rf / #"
        result = sandbox.run_in_sandbox([PYTHON, "-c", "import sys; print(sys.argv[1])", payload], cwd=self.ws)
        self.assertIn(payload, result.stdout)
        self.assertTrue(os.path.exists(tempfile.gettempdir()), "host filesystem must be untouched")

    def test_destroy_workspace_refuses_paths_outside_root(self):
        with self.assertRaises(sandbox.SandboxError):
            sandbox.destroy_workspace(os.environ.get("SystemRoot", "C:\\Windows"))
        with self.assertRaises(sandbox.SandboxError):
            sandbox.destroy_workspace(os.environ.get("SystemDrive", "C:") + "\\")

    def test_workspace_is_isolated_copy_under_workspace_dir(self):
        self.assertTrue(self.ws.startswith(WORKSPACE_DIR))
        self.assertNotEqual(self.ws, self.src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
