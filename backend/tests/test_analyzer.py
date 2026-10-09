import os
import sys
import shutil
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import analyzer

TMP = "/tmp/analyzer_unit_test"


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_generic_stdlib_http_project_supported(self):
        proj = os.path.join(TMP, "p1")
        write(os.path.join(proj, "app.py"),
              "import os\n"
              "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
              "class H(BaseHTTPRequestHandler):\n"
              "    def do_GET(self):\n"
              "        if self.path == '/health': pass\n"
              "if __name__ == '__main__':\n"
              "    port = int(os.environ.get('PORT', 8000))\n"
              "    HTTPServer(('0.0.0.0', port), H).serve_forever()\n")
        write(os.path.join(proj, "requirements.txt"), "")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["execution_status"], "SUPPORTED")
        self.assertEqual(profile["adapter"], "python_generic_http")
        self.assertIn("Python", profile["languages"])

    def test_flask_detected(self):
        proj = os.path.join(TMP, "p2")
        write(os.path.join(proj, "app.py"),
              "from flask import Flask\napp = Flask(__name__)\n"
              "@app.route('/x')\ndef x(): return 'ok'\napp.run(port=5000)\n")
        write(os.path.join(proj, "requirements.txt"), "flask\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Flask")
        self.assertIn(profile["execution_status"], ("SUPPORTED", "PARTIALLY_SUPPORTED"))
        paths = [e["path"] for e in profile["components"]["http_endpoints"]]
        self.assertIn("/x", paths)

    def test_django_analyzed_but_not_executable(self):
        proj = os.path.join(TMP, "p3")
        write(os.path.join(proj, "manage.py"), "import django\nfrom django.core.management import execute_from_command_line\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Django")
        self.assertEqual(profile["execution_status"], "ANALYZED_BUT_NOT_EXECUTABLE")

    def test_express_without_node_modules_partially_supported(self):
        proj = os.path.join(TMP, "p4")
        write(os.path.join(proj, "package.json"),
              '{"name":"x","dependencies":{"express":"^4.0.0"},"main":"index.js"}')
        write(os.path.join(proj, "index.js"), "const express = require('express');\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Express")
        self.assertEqual(profile["execution_status"], "PARTIALLY_SUPPORTED")
        # V39: this used to say the *sandbox* had no network access to run
        # npm install, which is misleading (npm install is never attempted;
        # the real issue is the project simply hasn't been set up yet) and
        # gave the user nothing to act on. It now names the actual command.
        self.assertIn("npm install", profile["execution_status_reason"])
        self.assertIn(proj, profile["execution_status_reason"])
        self.assertNotIn("network access", profile["execution_status_reason"])

    def test_express_with_hardcoded_port_partially_supported(self):
        # node_modules IS present here (unlike the test above), so this
        # exercises the PORT-env-var check specifically rather than the
        # earlier node_modules-missing short-circuit.
        proj = os.path.join(TMP, "p4b")
        write(os.path.join(proj, "package.json"),
              '{"name":"x","dependencies":{"express":"^4.0.0"},"main":"index.js"}')
        write(os.path.join(proj, "index.js"),
              "const express = require('express');\n"
              "const app = express();\n"
              "app.listen(8091, () => console.log('up'));\n")
        write(os.path.join(proj, "node_modules", "express", "index.js"), "module.exports = {};\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Express")
        self.assertEqual(profile["execution_status"], "PARTIALLY_SUPPORTED")
        self.assertIn("PORT", profile["execution_status_reason"])
        self.assertIn("TARGET_UNREACHABLE", profile["execution_status_reason"])

    def test_express_reading_port_env_supported(self):
        proj = os.path.join(TMP, "p4c")
        write(os.path.join(proj, "package.json"),
              '{"name":"x","dependencies":{"express":"^4.0.0"},"main":"index.js"}')
        write(os.path.join(proj, "index.js"),
              "const express = require('express');\n"
              "const app = express();\n"
              "const PORT = process.env.PORT || 8091;\n"
              "app.listen(PORT, () => console.log('up'));\n")
        write(os.path.join(proj, "node_modules", "express", "index.js"), "module.exports = {};\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Express")
        self.assertEqual(profile["execution_status"], "SUPPORTED")

    def test_express_destructured_port_env_supported(self):
        proj = os.path.join(TMP, "p4d")
        write(os.path.join(proj, "package.json"),
              '{"name":"x","dependencies":{"express":"^4.0.0"},"main":"index.js"}')
        write(os.path.join(proj, "index.js"),
              "const express = require('express');\n"
              "const app = express();\n"
              "const { PORT } = process.env;\n"
              "app.listen(PORT || 8091, () => console.log('up'));\n")
        write(os.path.join(proj, "node_modules", "express", "index.js"), "module.exports = {};\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Express")
        self.assertEqual(profile["execution_status"], "SUPPORTED")

    def test_unrecognized_language_unsupported(self):
        proj = os.path.join(TMP, "p5")
        write(os.path.join(proj, "Main.java"), "public class Main {}")
        # Toolchain presence is environment-dependent (this CI box may not have
        # a JDK); patch it present so this test verifies detection logic, not
        # what happens to be installed on whatever machine runs the suite.
        with patch("app.analyzer.shutil.which", return_value="/usr/bin/fake"):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["execution_status"], "SUPPORTED")

    def test_env_var_detection(self):
        proj = os.path.join(TMP, "p6")
        write(os.path.join(proj, "app.py"),
              "import os\nPORT = int(os.environ.get('PORT', '8000'))\nDB = os.getenv('DATABASE_URL')\n")
        profile = analyzer.analyze_project(proj)
        self.assertIn("PORT", profile["components"]["env_vars"])
        self.assertIn("DATABASE_URL", profile["components"]["env_vars"])

    # ---- AST-based analysis: regression tests for bugs found and fixed this pass ----

    def test_generic_dict_get_calls_are_not_false_positive_endpoints(self):
        proj = os.path.join(TMP, "p7")
        write(os.path.join(proj, "app.py"),
              "import os\n"
              "from http.server import BaseHTTPRequestHandler\n"
              "class H(BaseHTTPRequestHandler):\n"
              "    def do_GET(self):\n"
              "        port = os.environ.get('PORT', '8000')\n"
              "        qs = {}.get('delay', ['1'])\n"
              "        length = self.headers.get('Content-Length', 0)\n"
              "        if self.path == '/health': pass\n")
        profile = analyzer.analyze_project(proj)
        paths = {e["path"] for e in profile["components"]["http_endpoints"]}
        self.assertEqual(paths, {"/health"},
                          "generic .get() calls (dict/env/headers) must never be treated as routes")

    def test_resolves_open_with_os_path_join_variable(self):
        proj = os.path.join(TMP, "p8")
        write(os.path.join(proj, "app.py"),
              "import os\n"
              "SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'seed.json')\n"
              "with open(SEED_PATH) as f:\n"
              "    pass\n")
        profile = analyzer.analyze_project(proj)
        self.assertIn("data/seed.json", profile["components"]["filesystem_paths"])

    def test_fastapi_async_decorator_detected(self):
        proj = os.path.join(TMP, "p9")
        write(os.path.join(proj, "app.py"),
              "from fastapi import FastAPI\napp = FastAPI()\n"
              "@app.get('/items')\nasync def read_items():\n    return []\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "FastAPI")
        paths = {e["path"] for e in profile["components"]["http_endpoints"]}
        self.assertIn("/items", paths)

    def test_syntax_error_file_does_not_crash_analysis(self):
        proj = os.path.join(TMP, "p10")
        write(os.path.join(proj, "app.py"), "def broken(:\n    this is not python\n")
        profile = analyzer.analyze_project(proj)  # must not raise
        self.assertEqual(profile["components"]["static_analysis"]["python_files_with_syntax_errors"], 1)

    def test_plain_kotlin_cli_project_still_supported(self):
        # A real standalone Kotlin script must still be detected as runnable.
        proj = os.path.join(TMP, "p_plain_kotlin")
        write(os.path.join(proj, "Main.kt"),
              'fun main() {\n    println("hello from plain kotlin")\n}\n')
        # Toolchain presence is environment-dependent (this CI box may not have
        # kotlinc); patch it present so this test verifies detection logic, not
        # what happens to be installed on whatever machine runs the suite.
        with patch("app.analyzer.shutil.which", return_value="/usr/bin/fake"):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Kotlin")
        self.assertEqual(profile["execution_status"], "SUPPORTED")
        self.assertEqual(profile["adapter"], "kotlin_cli")

    def test_kotlin_cli_partially_supported_without_toolchain(self):
        # The other direction: when kotlinc genuinely isn't on PATH, the
        # project must be reported honestly rather than claimed SUPPORTED
        # and then fail to actually launch later.
        proj = os.path.join(TMP, "p_kotlin_missing_toolchain")
        write(os.path.join(proj, "Main.kt"),
              'fun main() {\n    println("hello from plain kotlin")\n}\n')
        with patch("app.analyzer.shutil.which", return_value=None):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["execution_status"], "PARTIALLY_SUPPORTED")
        self.assertIn("kotlinc", profile["execution_status_reason"])

    # ---- Streamlit / Gradio / ML-LLM / notebook / Docker detection ----

    def test_streamlit_analyzed_but_not_executable(self):
        # Streamlit needs `streamlit run`, a fundamentally different launch
        # model than `python <file>` -- must never be claimed SUPPORTED.
        proj = os.path.join(TMP, "p_streamlit")
        write(os.path.join(proj, "app.py"),
              "import streamlit as st\nst.write('hello')\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Streamlit")
        self.assertEqual(profile["execution_status"], "ANALYZED_BUT_NOT_EXECUTABLE")
        self.assertIsNone(profile["adapter"])
        self.assertIn("streamlit run", profile["execution_status_reason"])

    def test_gradio_missing_dependency_partially_supported(self):
        # gradio genuinely isn't installed in this sandbox and there's no
        # network to install it -- must be reported honestly, not SUPPORTED.
        proj = os.path.join(TMP, "p_gradio_missing")
        write(os.path.join(proj, "app.py"),
              "import gradio as gr\n"
              "gr.Interface(lambda x: x, 'text', 'text').launch()\n")
        with patch("app.analyzer.importlib.util.find_spec", return_value=None):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Gradio")
        self.assertEqual(profile["execution_status"], "PARTIALLY_SUPPORTED")
        self.assertIn("gradio", profile["execution_status_reason"])

    def test_gradio_installed_without_port_env_partially_supported(self):
        proj = os.path.join(TMP, "p_gradio_no_port")
        write(os.path.join(proj, "app.py"),
              "import gradio as gr\n"
              "gr.Interface(lambda x: x, 'text', 'text').launch()\n")
        with patch("app.analyzer.importlib.util.find_spec", return_value=object()):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Gradio")
        self.assertEqual(profile["execution_status"], "PARTIALLY_SUPPORTED")
        self.assertIn("PORT", profile["execution_status_reason"])

    def test_gradio_installed_with_port_env_supported(self):
        # Gradio launches exactly like generic Python HTTP once the PORT
        # contract is honored -- reuses that adapter rather than a new one.
        proj = os.path.join(TMP, "p_gradio_ok")
        write(os.path.join(proj, "app.py"),
              "import os, gradio as gr\n"
              "gr.Interface(lambda x: x, 'text', 'text').launch(\n"
              "    server_port=int(os.environ.get('PORT', 7860)))\n")
        with patch("app.analyzer.importlib.util.find_spec", return_value=object()):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Gradio")
        self.assertEqual(profile["execution_status"], "SUPPORTED")
        self.assertEqual(profile["adapter"], "python_generic_http")

    def test_ml_llm_missing_dependency_partially_supported(self):
        # torch genuinely isn't installed here and there's no network to
        # install it -- a plain-CLI misclassification would just crash later
        # with a raw ImportError instead of an honest upfront report.
        proj = os.path.join(TMP, "p_ml_missing")
        write(os.path.join(proj, "train.py"), "import torch\nprint(torch.__version__)\n")
        with patch("app.analyzer.importlib.util.find_spec", return_value=None):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "ML/LLM (Python)")
        self.assertEqual(profile["execution_status"], "PARTIALLY_SUPPORTED")
        self.assertIn("torch", profile["execution_status_reason"])

    def test_ml_llm_installed_supported_as_generic_cli(self):
        proj = os.path.join(TMP, "p_ml_ok")
        write(os.path.join(proj, "run.py"), "import openai\nprint('ready')\n")
        with patch("app.analyzer.importlib.util.find_spec", return_value=object()):
            profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "ML/LLM (Python)")
        self.assertEqual(profile["execution_status"], "SUPPORTED")
        self.assertEqual(profile["adapter"], "python_generic_cli")

    def test_jupyter_notebook_analyzed_but_not_executable(self):
        proj = os.path.join(TMP, "p_notebook")
        write(os.path.join(proj, "analysis.ipynb"), "{}")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Jupyter Notebook")
        self.assertEqual(profile["execution_status"], "ANALYZED_BUT_NOT_EXECUTABLE")
        self.assertIsNone(profile["adapter"])

    def test_docker_only_project_analyzed_but_not_executable(self):
        proj = os.path.join(TMP, "p_docker_only")
        write(os.path.join(proj, "Dockerfile"), "FROM python:3.12\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Docker/Containerized")
        self.assertEqual(profile["execution_status"], "ANALYZED_BUT_NOT_EXECUTABLE")
        self.assertIsNone(profile["adapter"])

    def test_dockerfile_alongside_real_framework_does_not_override_detection(self):
        # A Dockerfile shipped next to a genuinely runnable Flask app is the
        # common case, not the exception -- Docker-only detection must only
        # fire as a last-resort fallback, never shadow a real match.
        proj = os.path.join(TMP, "p_flask_plus_docker")
        write(os.path.join(proj, "app.py"),
              "from flask import Flask\napp = Flask(__name__)\napp.run(port=5000)\n")
        write(os.path.join(proj, "Dockerfile"), "FROM python:3.12\n")
        profile = analyzer.analyze_project(proj)
        self.assertEqual(profile["framework"], "Flask")


if __name__ == "__main__":
    unittest.main(verbosity=2)
