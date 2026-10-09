import os
import tempfile
import unittest

from app.api import _adapter_for_path, _build_ide_commands, _python_test_argv
from app import analyzer


class IdeRunnerRegressionTests(unittest.TestCase):
    def test_adapter_for_path_is_callable_from_route_module(self):
        self.assertEqual(_adapter_for_path("src/Luck.java", "unknown"), "java_cli")
        self.assertEqual(_adapter_for_path("main.py", "python_cli"), "python_cli")
        self.assertEqual(_adapter_for_path("app.js", "node_cli"), "node_cli")

    def test_python_test_command_never_requires_pytest(self):
        argv = _python_test_argv()
        self.assertEqual(argv[1], "-m")
        self.assertIn(argv[2], ("pytest", "unittest"))
        if argv[2] == "unittest":
            self.assertEqual(argv[3], "discover")

    def test_java_package_command_uses_workspace_root_classpath(self):
        with tempfile.TemporaryDirectory() as td:
            source = os.path.join(td, "src", "demo", "Luck.java")
            os.makedirs(os.path.dirname(source), exist_ok=True)
            with open(source, "w", encoding="utf-8") as f:
                f.write("package demo; public class Luck { public static void main(String[] a) {} }")
            argv, run = _build_ide_commands("java_cli", "src/demo/Luck.java", __import__('pathlib').Path(source), td)
            self.assertEqual(argv[:3], ["javac", "-d", "."])
            self.assertEqual(run, ["java", "-cp", ".", "demo.Luck"])

    def test_analyzer_does_not_mistake_test_strings_for_framework(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "tests"), exist_ok=True)
            with open(os.path.join(td, "app.py"), "w", encoding="utf-8") as f:
                f.write("print('hello')\n")
            with open(os.path.join(td, "tests", "test_analyzer.py"), "w", encoding="utf-8") as f:
                f.write("text = 'from flask import Flask\\napp.run(')\n")
            profile = analyzer.analyze_project(td)
            self.assertEqual(profile["framework"], "Python (generic/CLI)")
            self.assertEqual(profile["entrypoint"], "app.py")


if __name__ == "__main__":
    unittest.main()
