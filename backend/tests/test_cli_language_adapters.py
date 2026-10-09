import os
import sys
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import analyzer, chaos_engine, sandbox

TMP = "/tmp/cli_adapter_unit_test"


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestToolchainDetection(unittest.TestCase):
    """Every deterministic-CLI adapter (Java/C++/C/Go/Rust/Kotlin/PHP/Ruby)
    must report PARTIALLY_SUPPORTED — never a silently-broken SUPPORTED —
    when its compiler/interpreter isn't on PATH, and SUPPORTED when it is.
    Patches shutil.which so the result doesn't depend on what happens to be
    installed on whatever machine runs this suite."""

    CASES = [
        ("java_cli", "Main.java", "public class Main {}"),
        ("cpp_cli", "main.cpp", "int main(){return 0;}"),
        ("c_cli", "main.c", "int main(){return 0;}"),
        ("go_cli", "main.go", "package main\nfunc main(){}\n"),
        ("rust_cli", "main.rs", "fn main(){}\n"),
        ("kotlin_cli", "Main.kt", "fun main(){}\n"),
        ("php_cli", "index.php", "<?php\n"),
        ("ruby_cli", "main.rb", "puts 'hi'\n"),
    ]

    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_missing_toolchain_is_partially_supported_with_reason(self):
        for adapter, filename, content in self.CASES:
            with self.subTest(adapter=adapter):
                proj = os.path.join(TMP, adapter + "_missing")
                write(os.path.join(proj, filename), content)
                with patch("app.analyzer.shutil.which", return_value=None):
                    profile = analyzer.analyze_project(proj)
                self.assertEqual(profile["adapter"], adapter)
                self.assertEqual(profile["execution_status"], "PARTIALLY_SUPPORTED")
                self.assertIn("not found on PATH", profile["execution_status_reason"])

    def test_present_toolchain_is_supported(self):
        for adapter, filename, content in self.CASES:
            with self.subTest(adapter=adapter):
                proj = os.path.join(TMP, adapter + "_present")
                write(os.path.join(proj, filename), content)
                with patch("app.analyzer.shutil.which", return_value="/usr/bin/fake"):
                    profile = analyzer.analyze_project(proj)
                self.assertEqual(profile["adapter"], adapter)
                self.assertEqual(profile["execution_status"], "SUPPORTED")
                self.assertIsNone(profile["execution_status_reason"])


class TestLaunchArgvConstruction(unittest.TestCase):
    """Pure unit tests of the command chaos_engine.py builds per adapter —
    no process is actually started in this class."""

    def test_interpreted_languages_need_no_compile_step(self):
        cases = [
            ("go_cli", "main.go", ["go", "run", "main.go"]),
            ("php_cli", "index.php", ["php", "index.php"]),
            ("ruby_cli", "main.rb", ["ruby", "main.rb"]),
        ]
        for adapter, entry, expect in cases:
            with self.subTest(adapter=adapter):
                self.assertIsNone(chaos_engine._compile_argv(adapter, entry))
                self.assertEqual(
                    chaos_engine._launch_argv({"adapter": adapter, "entrypoint": entry}), expect
                )

    def test_compiled_languages_have_a_build_step_and_matching_run_command(self):
        cases = [
            ("java_cli", "Main.java", ["javac", "Main.java"], ["java", "Main"]),
            ("cpp_cli", "main.cpp", ["g++", "main.cpp", "-o", "chaos_cli_target"], ["./chaos_cli_target"]),
            ("c_cli", "main.c", ["gcc", "main.c", "-o", "chaos_cli_target"], ["./chaos_cli_target"]),
            ("rust_cli", "main.rs", ["rustc", "main.rs", "-o", "chaos_cli_target"], ["./chaos_cli_target"]),
            ("kotlin_cli", "Main.kt",
             ["kotlinc", "Main.kt", "-include-runtime", "-d", "chaos_cli_target.jar"],
             ["java", "-jar", "chaos_cli_target.jar"]),
        ]
        for adapter, entry, compile_expect, run_expect in cases:
            with self.subTest(adapter=adapter):
                self.assertEqual(chaos_engine._compile_argv(adapter, entry), compile_expect)
                self.assertEqual(
                    chaos_engine._launch_argv({"adapter": adapter, "entrypoint": entry}), run_expect
                )

    def test_unmapped_adapter_or_missing_entrypoint_returns_none(self):
        self.assertIsNone(chaos_engine._launch_argv({"adapter": "java_cli", "entrypoint": None}))
        self.assertIsNone(chaos_engine._launch_argv({"adapter": "totally_unknown", "entrypoint": "x"}))


@unittest.skipUnless(shutil.which("gcc"), "gcc not available in this environment")
class TestRealCCompileAndRun(unittest.TestCase):
    """Genuine end-to-end proof, not a mock: actually compiles and runs a C
    program through the real sandbox workspace — the exact path a real C
    chaos experiment takes today via _start_and_wait -> _compile_if_needed."""

    def setUp(self):
        self.src = os.path.join(TMP, "c_src")
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(self.src)
        self.ws = None

    def tearDown(self):
        if self.ws:
            sandbox.destroy_workspace(self.ws)
        shutil.rmtree(TMP, ignore_errors=True)

    def test_compiles_and_runs_for_real(self):
        write(os.path.join(self.src, "main.c"),
              '#include <stdio.h>\nint main(){printf("chaos-tutor-c-ok\\n");return 0;}\n')
        self.ws = sandbox.make_workspace(self.src, "test")
        profile = {"adapter": "c_cli", "entrypoint": "main.c"}
        chaos_engine._compile_if_needed(profile, self.ws)
        self.assertTrue(os.path.exists(os.path.join(self.ws, "chaos_cli_target")))
        argv = chaos_engine._launch_argv(profile)
        result = sandbox.run_in_sandbox(argv, cwd=self.ws)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("chaos-tutor-c-ok", result.stdout)

    def test_compile_failure_raises_compile_error_with_real_compiler_output(self):
        write(os.path.join(self.src, "main.c"), "this is not valid C at all {{{\n")
        self.ws = sandbox.make_workspace(self.src, "test")
        profile = {"adapter": "c_cli", "entrypoint": "main.c"}
        with self.assertRaises(chaos_engine.CompileError) as ctx:
            chaos_engine._compile_if_needed(profile, self.ws)
        self.assertIn("gcc", str(ctx.exception))


@unittest.skipUnless(shutil.which("g++"), "g++ not available in this environment")
class TestRealCppCompileAndRun(unittest.TestCase):
    def setUp(self):
        self.src = os.path.join(TMP, "cpp_src")
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(self.src)
        self.ws = None

    def tearDown(self):
        if self.ws:
            sandbox.destroy_workspace(self.ws)
        shutil.rmtree(TMP, ignore_errors=True)

    def test_compiles_and_runs_for_real(self):
        write(os.path.join(self.src, "main.cpp"),
              '#include <iostream>\nint main(){std::cout << "chaos-tutor-cpp-ok" << std::endl; return 0;}\n')
        self.ws = sandbox.make_workspace(self.src, "test")
        profile = {"adapter": "cpp_cli", "entrypoint": "main.cpp"}
        chaos_engine._compile_if_needed(profile, self.ws)
        argv = chaos_engine._launch_argv(profile)
        result = sandbox.run_in_sandbox(argv, cwd=self.ws)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("chaos-tutor-cpp-ok", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
