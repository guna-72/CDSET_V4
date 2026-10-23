from __future__ import annotations
"""
Project Intelligence (spec section 14).

Walks an already-safely-extracted project directory and produces a
normalized ProjectProfile: languages, framework, components (HTTP
endpoints, env vars, filesystem access, subprocess calls, DB references),
dependencies, and an honest execution_status.

execution_status values (spec section 9):
  SUPPORTED                  - can actually be started and chaos-tested
                                with what's available in THIS environment
  PARTIALLY_SUPPORTED        - framework detected/adapted, but some
                                dependencies can't be satisfied here
  ANALYZED_BUT_NOT_EXECUTABLE- language/structure understood, no execution
                                adapter available (or deps unmet, no
                                network to install them)
  UNSUPPORTED                - nothing we recognize
"""
import ast
import importlib.util
import json
import os
import re
import shutil

from app.config import SYSTEM_ENV_KEYS

LANGUAGE_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".java": "Java", ".c": "C", ".h": "C", ".cpp": "C++",
    ".hpp": "C++", ".kt": "Kotlin", ".sh": "Shell", ".html": "HTML", ".css": "CSS",
    ".go": "Go", ".rb": "Ruby", ".rs": "Rust", ".php": "PHP",
}

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "venv", ".venv", "env",
    "dist", "build", "target", ".idea", ".vscode", ".next", "coverage",
    "out", ".turbo", ".cache", "bower_components", ".pytest_cache", ".mypy_cache",
}

# Recognized ML/LLM libraries for classification + honest dependency
# reporting. Import-name keyed (not pip package name — sklearn's pip name is
# "scikit-learn" but its import is "sklearn"); mostly large and/or
# GPU-oriented packages a minimal, no-network sandbox is unlikely to have.
_ML_LLM_MODULES = {
    "torch", "tensorflow", "keras", "sklearn", "transformers",
    "xgboost", "lightgbm", "openai", "anthropic", "langchain",
    "llama_index", "cohere", "spacy",
}

# Standard library modules that don't need a pip install to satisfy.
_STDLIB_CACHE = None


def _is_stdlib(module_name: str) -> bool:
    global _STDLIB_CACHE
    if _STDLIB_CACHE is None:
        import sys
        _STDLIB_CACHE = set(sys.stdlib_module_names)
    top = module_name.split(".")[0]
    return top in _STDLIB_CACHE


def analyze_project(project_dir: str) -> dict:
    file_list = []
    lang_counts = {}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            path = os.path.join(root, f)
            rel = os.path.relpath(path, project_dir)
            file_list.append(rel)
            ext = os.path.splitext(f)[1].lower()
            if ext in LANGUAGE_BY_EXT:
                lang = LANGUAGE_BY_EXT[ext]
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

    structure = _detect_structure(project_dir, file_list)
    py_files = [f for f in file_list if f.endswith(".py")]
    has_package_json = "package.json" in file_list

    framework, entrypoint, exec_status, reason, adapter = _detect_framework(
        project_dir, file_list, py_files, has_package_json
    )

    components = _detect_components(project_dir, py_files, file_list, framework)

    profile = {
        "languages": lang_counts,
        "framework": framework,
        "adapter": adapter,
        "entrypoint": entrypoint,
        "execution_status": exec_status,
        "execution_status_reason": reason,
        "structure": structure,
        "components": components,
        "file_count": len(file_list),
    }
    return profile


def _detect_structure(project_dir, file_list):
    markers = ["requirements.txt", "pyproject.toml", "package.json", "Dockerfile",
               "docker-compose.yml", "README.md", "setup.py", "Pipfile"]
    present = [m for m in markers if m in file_list]
    top_level_dirs = sorted({f.split(os.sep)[0] for f in file_list if os.sep in f})
    return {"marker_files": present, "top_level_dirs": top_level_dirs[:30]}


def _read(project_dir, rel, max_bytes=512 * 1024):
    try:
        with open(os.path.join(project_dir, rel), "r", errors="ignore") as f:
            return f.read(max_bytes)
    except OSError:
        return ""


def _python_imports(project_dir, py_files):
    """Return real top-level imports from parseable Python files.

    Raw text matching is intentionally avoided: test files and documentation
    can mention framework names without actually using those frameworks.
    """
    modules = set()
    for f in py_files:
        try:
            tree = ast.parse(_read(project_dir, f), filename=f)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split('.')[0])
    return modules


# Chaos experiments that start a service allocate a fresh, unused port per
# run and inject it via the PORT env var (app/chaos_engine.py::_start_and_wait);
# they never target whatever port a project's source hardcodes. A project
# whose entrypoint doesn't read that env var will always time out as
# TARGET_UNREACHABLE regardless of sandbox/isolation health, so that's
# surfaced here as an honest PARTIALLY_SUPPORTED reason instead of only
# showing up later as an opaque "test target could not be reached" result.
_PORT_ENV_PATTERNS = {
    "node": (
        r"process\.env\.PORT\b",
        r"process\.env\[\s*['\"]PORT['\"]\s*\]",
        r"\{[^}]*\bPORT\b[^}]*\}\s*=\s*process\.env\b",
    ),
    "python": (
        r"os\.environ\.get\(\s*['\"]PORT['\"]",
        r"os\.environ\[\s*['\"]PORT['\"]\s*\]",
        r"os\.getenv\(\s*['\"]PORT['\"]",
    ),
}


def _reads_port_env(source: str, language: str) -> bool:
    return any(re.search(p, source) for p in _PORT_ENV_PATTERNS.get(language, ()))


def _node_source(project_dir, file_list) -> str:
    js_files = [
        f for f in file_list
        if f.lower().endswith((".js", ".mjs", ".cjs"))
        and not f.startswith("node_modules" + os.sep)
        and not f.lower().endswith((".min.js", ".bundle.js", ".chunk.js", ".map"))
    ]
    return "\n".join(_read(project_dir, f) for f in js_files[:50])


_NO_PORT_ENV_REASON_NODE = (
    "{framework} adapter available, but no code path reading the PORT "
    "environment variable (e.g. process.env.PORT) was found. Chaos "
    "experiments that start a service assign a fresh, unused port per run "
    "and pass it via PORT — a server that only listens on a hardcoded port "
    "number will never be reached, and every network-fault experiment will "
    "report TARGET_UNREACHABLE regardless of sandbox health. Add "
    "`const PORT = process.env.PORT || <default>;` (or equivalent) before "
    "the listen call."
)
_NO_PORT_ENV_REASON_PYTHON = (
    "{framework} adapter available, but no code path reading the PORT "
    "environment variable (e.g. os.environ.get('PORT')) was found. Chaos "
    "experiments that start a service assign a fresh, unused port per run "
    "and pass it via PORT — a server that only listens on a hardcoded port "
    "number will never be reached, and every network-fault experiment will "
    "report TARGET_UNREACHABLE regardless of sandbox health. Read the PORT "
    "env var (with a fallback default) before binding."
)


def _detect_framework(project_dir, file_list, py_files, has_package_json):
    """Returns (framework, entrypoint, execution_status, reason, adapter)."""
    py_source = ""
    for f in py_files:
        py_source += _read(project_dir, f) + "\n"
    imported_modules = _python_imports(project_dir, py_files)

    # ---- Python frameworks ----
    if "flask" in imported_modules:
        missing = _missing_python_deps(project_dir, file_list, {"flask"})
        entrypoint = _find_python_entrypoint(project_dir, py_files, "app.run")
        if missing:
            return ("Flask", entrypoint, "PARTIALLY_SUPPORTED",
                    f"Flask adapter available, but dependency not importable in this "
                    f"sandbox and no network to install it: {', '.join(missing)}", "python_flask")
        if not _reads_port_env(py_source, "python"):
            return ("Flask", entrypoint, "PARTIALLY_SUPPORTED",
                    _NO_PORT_ENV_REASON_PYTHON.format(framework="Flask"), "python_flask")
        return ("Flask", entrypoint, "SUPPORTED", None, "python_flask")

    if "fastapi" in imported_modules:
        missing = _missing_python_deps(project_dir, file_list, {"fastapi", "uvicorn"})
        entrypoint = _find_python_entrypoint(project_dir, py_files, "uvicorn.run")
        if missing:
            return ("FastAPI", entrypoint, "PARTIALLY_SUPPORTED",
                    f"FastAPI adapter available, but dependency not importable in this "
                    f"sandbox and no network to install it: {', '.join(missing)}", "python_fastapi")
        if not _reads_port_env(py_source, "python"):
            return ("FastAPI", entrypoint, "PARTIALLY_SUPPORTED",
                    _NO_PORT_ENV_REASON_PYTHON.format(framework="FastAPI"), "python_fastapi")
        return ("FastAPI", entrypoint, "SUPPORTED", None, "python_fastapi")

    if "django" in imported_modules:
        return ("Django", None, "ANALYZED_BUT_NOT_EXECUTABLE",
                "Django execution adapter is out of MVP scope (spec section 30, future work)",
                None)

    if "streamlit" in imported_modules:
        entrypoint = _find_python_entrypoint(project_dir, py_files, None)
        return ("Streamlit", entrypoint, "ANALYZED_BUT_NOT_EXECUTABLE",
                "Streamlit app — launched via the `streamlit run` CLI, which runs "
                "the script inside Streamlit's own session/rerun runtime rather "
                "than a plain `python <file>` process; no execution adapter for "
                "that launch model yet (spec section 30, future work)", None)

    if "gradio" in imported_modules:
        missing = _missing_python_deps(project_dir, file_list, {"gradio"})
        entrypoint = _find_python_entrypoint(project_dir, py_files, None)
        if missing:
            return ("Gradio", entrypoint, "PARTIALLY_SUPPORTED",
                    f"Gradio adapter available, but dependency not importable in "
                    f"this sandbox and no network to install it: {', '.join(missing)}",
                    "python_generic_http")
        # Gradio launches like any other Python HTTP process (`python <file>`,
        # demo.launch() binds a port) — reuse the generic HTTP adapter rather
        # than inventing a new one, but it's still held to the same PORT-env
        # contract every service adapter needs (see _NO_PORT_ENV_REASON_PYTHON).
        if not _reads_port_env(py_source, "python"):
            return ("Gradio", entrypoint, "PARTIALLY_SUPPORTED",
                    _NO_PORT_ENV_REASON_PYTHON.format(framework="Gradio"),
                    "python_generic_http")
        return ("Gradio", entrypoint, "SUPPORTED", None, "python_generic_http")

    ml_llm_hits = sorted(imported_modules & _ML_LLM_MODULES)
    if ml_llm_hits:
        missing = _missing_python_deps(project_dir, file_list, set(ml_llm_hits))
        entrypoint = _find_python_entrypoint(project_dir, py_files, None)
        if missing:
            return ("ML/LLM (Python)", entrypoint, "PARTIALLY_SUPPORTED",
                    f"ML/LLM libraries detected ({', '.join(ml_llm_hits)}), but not "
                    f"importable in this sandbox and no network to install them: "
                    f"{', '.join(missing)}. These are typically large and/or "
                    f"GPU-oriented packages — install them into the environment "
                    f"running this backend before chaos-testing this project.",
                    "python_generic_cli")
        # No HTTP framework matched above, so this is treated as a plain
        # script (train/inference/eval run-to-completion), same launch as
        # any other generic Python CLI.
        return ("ML/LLM (Python)", entrypoint, "SUPPORTED", None, "python_generic_cli")

    # ---- Node frameworks ----
    if has_package_json:
        pkg = _read(project_dir, "package.json")
        try:
            pkg_json = json.loads(pkg)
        except json.JSONDecodeError:
            pkg_json = {}
        deps = {**pkg_json.get("dependencies", {}), **pkg_json.get("devDependencies", {})}
        # node_modules itself is in IGNORE_DIRS (os.walk never descends into
        # it, to avoid walking a project's entire dependency tree), so it
        # can never show up in file_list — checked directly on disk instead,
        # or this always reports "not present" even when it genuinely is.
        node_modules_present = os.path.isdir(os.path.join(project_dir, "node_modules"))
        entrypoint = pkg_json.get("main") or _guess_node_entry(project_dir, file_list)

        if "express" in deps:
            if not node_modules_present:
                return ("Express", entrypoint, "PARTIALLY_SUPPORTED",
                        "Express adapter available, but node_modules is not present. Run "
                        f"`npm install` in the project folder ({project_dir}) and re-analyze.",
                        "node_express")
            node_src = _node_source(project_dir, file_list)
            if not _reads_port_env(node_src, "node"):
                return ("Express", entrypoint, "PARTIALLY_SUPPORTED",
                        _NO_PORT_ENV_REASON_NODE.format(framework="Express"), "node_express")
            return ("Express", entrypoint, "SUPPORTED", None, "node_express")

        if "react" in deps or "next" in deps:
            return ("React/Next.js", entrypoint, "ANALYZED_BUT_NOT_EXECUTABLE",
                    "Frontend framework, not an HTTP service to chaos-test directly "
                    "(spec section 30, future work)", None)

        # Plain Node app with no framework deps at all -> generic HTTP,
        # runnable with the bundled `node` binary, no npm install needed.
        if not deps:
            node_src = _node_source(project_dir, file_list)
            if not _reads_port_env(node_src, "node"):
                return ("Node (generic)", entrypoint, "PARTIALLY_SUPPORTED",
                        _NO_PORT_ENV_REASON_NODE.format(framework="Node (generic)"), "node_generic")
            return ("Node (generic)", entrypoint, "SUPPORTED", None, "node_generic")
        return ("Node (unrecognized framework)", entrypoint, "PARTIALLY_SUPPORTED",
                f"package.json declares dependencies {list(deps)[:5]} that aren't "
                f"installed and can't be installed here (no network)", "node_generic")

    # ---- Generic Python HTTP (stdlib only, e.g. http.server) ----
    if py_files and re.search(r"http\.server|socketserver|wsgiref", py_source):
        entrypoint = _find_python_entrypoint(project_dir, py_files, None)
        if not _reads_port_env(py_source, "python"):
            return ("Generic HTTP (Python stdlib)", entrypoint, "PARTIALLY_SUPPORTED",
                    _NO_PORT_ENV_REASON_PYTHON.format(framework="Generic HTTP (Python stdlib)"),
                    "python_generic_http")
        return ("Generic HTTP (Python stdlib)", entrypoint, "SUPPORTED", None, "python_generic_http")

    # ---- Plain Python CLI / script, no HTTP surface detected ----
    if py_files:
        entrypoint = _find_python_entrypoint(project_dir, py_files, None)
        return ("Python (generic/CLI)", entrypoint, "SUPPORTED", None, "python_generic_cli")

    # ---- Standalone / project languages with deterministic CLI adapters ----
    # These adapters intentionally execute through the sandbox with fixed argv;
    # no shell command is ever constructed from project contents.
    java_files = [f for f in file_list if f.lower().endswith(".java")]
    if java_files:
        entrypoint = _choose_source_entry(file_list, java_files, ("Main.java", "App.java", "Program.java", "Luck.java"))
        missing = _missing_toolchain("java_cli")
        if missing:
            return ("Java", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install a JDK "
                     "(not just a JRE) to compile and run this project", "java_cli")
        return ("Java", entrypoint, "SUPPORTED", None, "java_cli")

    cpp_files = [f for f in file_list if f.lower().endswith((".cpp", ".cc", ".cxx"))]
    if cpp_files:
        entrypoint = _choose_source_entry(file_list, cpp_files, ("main.cpp", "Main.cpp"))
        missing = _missing_toolchain("cpp_cli")
        if missing:
            return ("C++", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install a C++ "
                     "compiler to build and run this project", "cpp_cli")
        return ("C++", entrypoint, "SUPPORTED", None, "cpp_cli")

    c_files = [f for f in file_list if f.lower().endswith(".c")]
    if c_files:
        entrypoint = _choose_source_entry(file_list, c_files, ("main.c", "Main.c"))
        missing = _missing_toolchain("c_cli")
        if missing:
            return ("C", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install a C "
                     "compiler to build and run this project", "c_cli")
        return ("C", entrypoint, "SUPPORTED", None, "c_cli")

    go_files = [f for f in file_list if f.lower().endswith(".go")]
    if go_files:
        entrypoint = _choose_source_entry(file_list, go_files, ("main.go",))
        missing = _missing_toolchain("go_cli")
        if missing:
            return ("Go", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install the Go "
                     "toolchain to run this project", "go_cli")
        return ("Go", entrypoint, "SUPPORTED", None, "go_cli")

    rust_files = [f for f in file_list if f.lower().endswith(".rs")]
    if rust_files:
        entrypoint = _choose_source_entry(file_list, rust_files, ("main.rs",))
        missing = _missing_toolchain("rust_cli")
        if missing:
            return ("Rust", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install Rust "
                     "(rustc) to build and run this project", "rust_cli")
        return ("Rust", entrypoint, "SUPPORTED", None, "rust_cli")

    kotlin_files = [f for f in file_list if f.lower().endswith(".kt")]
    if kotlin_files:
        entrypoint = _choose_source_entry(file_list, kotlin_files, ("Main.kt",))
        missing = _missing_toolchain("kotlin_cli")
        if missing:
            return ("Kotlin", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install the "
                     "Kotlin compiler to build and run this project", "kotlin_cli")
        return ("Kotlin", entrypoint, "SUPPORTED", None, "kotlin_cli")

    php_files = [f for f in file_list if f.lower().endswith(".php")]
    if php_files:
        entrypoint = _choose_source_entry(file_list, php_files, ("index.php", "main.php"))
        missing = _missing_toolchain("php_cli")
        if missing:
            return ("PHP", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install PHP "
                     "to run this project", "php_cli")
        return ("PHP", entrypoint, "SUPPORTED", None, "php_cli")

    ruby_files = [f for f in file_list if f.lower().endswith(".rb")]
    if ruby_files:
        entrypoint = _choose_source_entry(file_list, ruby_files, ("main.rb",))
        missing = _missing_toolchain("ruby_cli")
        if missing:
            return ("Ruby", entrypoint, "PARTIALLY_SUPPORTED",
                     f"{'/'.join(missing)} not found on PATH — install Ruby "
                     "to run this project", "ruby_cli")
        return ("Ruby", entrypoint, "SUPPORTED", None, "ruby_cli")

    node_files = [f for f in file_list if f.lower().endswith(".js")]
    if node_files:
        entrypoint = _choose_source_entry(file_list, node_files, ("index.js", "main.js", "app.js"))
        node_src = _node_source(project_dir, file_list)
        if not _reads_port_env(node_src, "node"):
            return ("Node.js", entrypoint, "PARTIALLY_SUPPORTED",
                    _NO_PORT_ENV_REASON_NODE.format(framework="Node.js"), "node_generic")
        return ("Node.js", entrypoint, "SUPPORTED", None, "node_generic")

    # ---- Non-language project shapes: nothing above matched a runnable ----
    # ---- source file, but the project shape itself is still recognizable ----
    ipynb_files = [f for f in file_list if f.lower().endswith(".ipynb")]
    if ipynb_files:
        return ("Jupyter Notebook", None, "ANALYZED_BUT_NOT_EXECUTABLE",
                f"{len(ipynb_files)} notebook file(s) found, no standalone script "
                "entrypoint. Notebooks run cell-by-cell inside a kernel session, "
                "not as a single process this sandbox can launch and health-check; "
                "export to a .py script to make this project runnable here "
                "(spec section 30, future work)", None)

    if file_list and ("Dockerfile" in file_list or "docker-compose.yml" in file_list
                       or "docker-compose.yaml" in file_list):
        return ("Docker/Containerized", None, "ANALYZED_BUT_NOT_EXECUTABLE",
                "Only Docker packaging (Dockerfile/docker-compose) found, no "
                "directly-runnable source recognized. This sandbox launches "
                "projects as a plain host process, not via `docker build`/"
                "`docker compose up`; no container-orchestration adapter yet "
                "(spec section 30, future work)", None)

    return (None, None, "UNSUPPORTED", "no recognized executable language/framework found", None)


def _choose_source_entry(file_list, candidates, preferred):
    by_name = {os.path.basename(f).lower(): f for f in candidates}
    for name in preferred:
        if name.lower() in by_name:
            return by_name[name.lower()]
    return sorted(candidates, key=lambda x: (x.count(os.sep), len(x), x.lower()))[0]


# Compiler/interpreter binaries chaos_engine.py's launch step actually needs
# for each deterministic CLI adapter. Checked with shutil.which() against the
# PATH of the host actually running the backend (Windows or Linux) — never
# assumed present. Kept in one place so analyzer.py's reported status and
# chaos_engine.py's launch logic can never silently drift apart.
TOOLCHAIN_FOR_ADAPTER = {
    "java_cli": ("javac", "java"),
    "cpp_cli": ("g++",),
    "c_cli": ("gcc",),
    "go_cli": ("go",),
    "rust_cli": ("rustc",),
    "kotlin_cli": ("kotlinc",),
    "php_cli": ("php",),
    "ruby_cli": ("ruby",),
}


def _missing_toolchain(adapter):
    """Returns the subset of TOOLCHAIN_FOR_ADAPTER[adapter] not found on
    PATH, or [] if everything the adapter needs to actually compile/run is
    present. An adapter with no entry here (e.g. the Python/Node adapters)
    is assumed to need nothing beyond the interpreter this backend itself
    runs under, which is checked elsewhere."""
    return [b for b in TOOLCHAIN_FOR_ADAPTER.get(adapter, ()) if shutil.which(b) is None]


def _missing_python_deps(project_dir, file_list, required_modules):
    missing = []
    for mod in required_modules:
        if _is_stdlib(mod):
            continue
        if importlib.util.find_spec(mod) is None:
            missing.append(mod)
    return missing


def _find_python_entrypoint(project_dir, py_files, run_call_signature):
    """Choose an application entrypoint without mistaking tests for apps."""
    preferred = {"app.py", "main.py", "server.py", "run.py"}
    candidates = [f for f in py_files if os.path.basename(f).lower() in preferred]

    def has_call(path, dotted_name):
        if not dotted_name:
            return False
        try:
            tree = ast.parse(_read(project_dir, path), filename=path)
        except SyntaxError:
            return False
        wanted = dotted_name.split('.')
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if len(wanted) == 2 and isinstance(func, ast.Attribute) and func.attr == wanted[1] and isinstance(func.value, ast.Name) and func.value.id == wanted[0]:
                return True
            if len(wanted) == 1 and isinstance(func, ast.Name) and func.id == wanted[0]:
                return True
        return False

    for f in candidates:
        if has_call(f, run_call_signature):
            return f

    for f in candidates:
        try:
            tree = ast.parse(_read(project_dir, f), filename=f)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                if isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__":
                    return f

    for f in py_files:
        normalized = f.replace('\\', '/').lower()
        if '/test' in normalized or normalized.startswith('test_') or '/tests/' in normalized:
            continue
        if has_call(f, run_call_signature):
            return f

    if candidates:
        return candidates[0]
    return _best_effort_python_entry(project_dir, py_files)


_APP_FACTORY_CALLS = {"create_app", "Flask", "FastAPI", "Starlette", "Quart", "Sanic", "Bottle", "make_app"}
_NOT_AN_ENTRY_STEMS = {"config", "configs", "settings", "setup", "conftest", "__init__", "constants",
                       "extensions", "models", "forms", "utils", "errors", "exceptions", "version", "_version"}


def _best_effort_python_entry(project_dir, py_files):
    """Last resort when no app.py/main.py/... exists. This used to be the
    alphabetically first file, so a real project like miguelgrinberg/microblog
    reported config.py as its entry point. Rank instead: never tests, prefer
    files that build an app (create_app()/Flask()/...) or have a __main__
    block, avoid config/settings/setup-style modules, prefer the project root."""
    if not py_files:
        return None

    def profile(path):
        try:
            tree = ast.parse(_read(project_dir, path), filename=path)
        except (SyntaxError, ValueError, OSError):
            return None                      # unparseable: rank below any parseable file
        builds_app = has_main = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if name in _APP_FACTORY_CALLS:
                    builds_app = True
            elif (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                  and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"):
                has_main = True
        return builds_app, has_main

    def rank(path):
        norm = path.replace("\\", "/").lower()
        stem = os.path.splitext(os.path.basename(norm))[0]
        is_test = ("/test" in "/" + norm or stem.startswith("test") or stem.endswith("_test")
                   or stem in {"tests", "conftest"})
        parsed = profile(path)
        builds_app, has_main = parsed if parsed else (False, False)
        return (is_test, parsed is None, stem in _NOT_AN_ENTRY_STEMS, not builds_app, not has_main,
                norm.count("/"), norm)

    return min(py_files, key=rank)


def _guess_node_entry(project_dir, file_list):
    for name in ("index.js", "server.js", "app.js"):
        if name in file_list:
            return name
    js_files = [f for f in file_list if f.endswith(".js") and "node_modules" not in f]
    return js_files[0] if js_files else None


def _detect_components(project_dir, py_files, file_list, framework):
    endpoints = []
    env_vars = set()
    filesystem_access = set()
    subprocess_calls = 0
    db_signals = set()

    # ---- Python: AST-based (real parse, not regex) ----
    py_ast_ok = 0
    py_ast_failed = 0
    py_source_for_port = ""
    for f in py_files:
        source = _read(project_dir, f)
        py_source_for_port += source + "\n"
        try:
            tree = ast.parse(source, filename=f)
        except SyntaxError:
            py_ast_failed += 1
            continue
        py_ast_ok += 1
        visitor = _PyVisitor()
        visitor.visit(tree)
        endpoints.extend(visitor.endpoints)
        env_vars.update(visitor.env_vars)
        filesystem_access.update(visitor.filesystem_paths)
        subprocess_calls += visitor.subprocess_calls
        db_signals.update(visitor.db_signals)

    # ---- Node/JS: regex (ast module can't parse JS) ----
    js_source = ""
    for f in file_list:
        fl = f.lower()
        if (fl.endswith((".js", ".ts", ".mjs", ".cjs"))
                and not fl.endswith((".min.js", ".bundle.js", ".chunk.js", ".map", ".d.ts"))
                and "node_modules" not in f):
            js_source += _read(project_dir, f) + "\n"
    for m in re.finditer(r'app\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', js_source):
        endpoints.append({"method": m.group(1).upper(), "path": m.group(2)})
    # Raw Node `http.createServer` style: routing via
    # `req.method === 'POST' && parsed.pathname === '/items'` on one line.
    for line in js_source.splitlines():
        if len(line) > 1000 or "pathname" not in line:
            continue
        path_m = re.search(r'pathname\s*===\s*["\']([^"\']+)["\']', line)
        if not path_m:
            continue
        method_m = re.search(r"req\.method\s*===\s*['\"](GET|POST|PUT|DELETE|PATCH)['\"]", line)
        endpoints.append({"method": method_m.group(1) if method_m else "GET", "path": path_m.group(1)})
    for m in re.finditer(r'process\.env\.([A-Z0-9_]+)', js_source):
        env_vars.add(m.group(1))
    subprocess_calls += len(re.findall(r'child_process\.', js_source))
    for pattern, label in [(r'\bredis\b', "Redis"), (r'mongodb|mongoose', "MongoDB"),
                            (r'\bpg\b|postgres', "PostgreSQL"), (r'mysql', "MySQL")]:
        if re.search(pattern, js_source, re.IGNORECASE):
            db_signals.add(label)

    seen = set()
    uniq_endpoints = []
    for e in endpoints:
        key = (e["method"], e["path"])
        if key not in seen:
            seen.add(key)
            uniq_endpoints.append(e)

    port = None
    m = re.search(r'\.run\([^)]*port\s*=\s*(\d+)', py_source_for_port)
    if m:
        port = int(m.group(1))
    else:
        m = (re.search(r'listen\(\s*(\d+)', js_source)
             or re.search(r'HTTPServer\(\(\s*["\'][^"\']*["\']\s*,\s*(\d+)\s*\)', py_source_for_port))
        if m:
            port = int(m.group(1))

    return {
        "http_endpoints": uniq_endpoints,
        "env_vars": sorted(v for v in env_vars if v.upper() not in SYSTEM_ENV_KEYS),
        "filesystem_paths": sorted(filesystem_access),
        "subprocess_call_count": subprocess_calls,
        "database_signals": sorted(db_signals),
        "detected_port": port,
        "static_analysis": {"python_files_parsed": py_ast_ok, "python_files_with_syntax_errors": py_ast_failed},
    }


def _resolve_join_call(call_node) -> str | None:
    """Best-effort resolution of `os.path.join(<dynamic...>, "lit", "eral")`
    -> "lit/eral": takes the trailing run of literal-string args (the
    common `os.path.join(os.path.dirname(__file__), "data", "x.json")`
    idiom), dropping the leading dynamic part since failure-surface
    discovery only needs a project-relative suffix anyway. Returns None
    if it isn't an os.path.join call or has no literal tail."""
    func = call_node.func
    is_os_path_join = (
        isinstance(func, ast.Attribute) and func.attr == "join"
        and isinstance(func.value, ast.Attribute) and func.value.attr == "path"
        and isinstance(func.value.value, ast.Name) and func.value.value.id == "os"
    )
    if not is_os_path_join:
        return None
    tail = []
    for arg in call_node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            tail.append(arg.value)
        else:
            tail = []  # reset — only the run after the last dynamic arg counts
    return "/".join(tail) if tail else None


class _PyVisitor(ast.NodeVisitor):
    """Real AST-based detection for Python files — replaces the previous
    regex-only approach. Resolves simple constant propagation (e.g.
    `SEED_PATH = "data/seed.json"` ... `open(SEED_PATH)`), which regex
    could never do; that gap was documented in this session's first MVP
    pass and is now fixed for the single-hop case (a Name bound exactly
    once at module level to a string constant). Multi-hop / conditional
    assignment still won't resolve — real data-flow analysis is beyond a
    lightweight visitor, and remains an honest, documented approximation."""

    _DB_IMPORTS = {
        "psycopg2": "PostgreSQL", "asyncpg": "PostgreSQL",
        "pymongo": "MongoDB", "motor": "MongoDB",
        "redis": "Redis", "aioredis": "Redis",
        "mysql": "MySQL", "pymysql": "MySQL", "MySQLdb": "MySQL",
        "sqlite3": "SQLite",
    }
    _HTTP_METHOD_NAMES = {"get", "post", "put", "delete", "patch"}
    _HANDLER_METHODS = {"do_GET": "GET", "do_POST": "POST", "do_PUT": "PUT", "do_DELETE": "DELETE"}

    def __init__(self):
        self.endpoints = []
        self.env_vars = set()
        self.filesystem_paths = set()
        self.subprocess_calls = 0
        self.db_signals = set()
        self._string_constants = {}  # name -> resolved str value (single-hop only)
        self._current_handler_method = None

    def visit_Module(self, node):
        # Pass 0: collect `NAME = "literal"` and `NAME = os.path.join(..., "literal", "tail")`
        # bindings anywhere in the module so open(NAME) can resolve them.
        # If a name is assigned more than once we drop it rather than
        # guess which value is live at call time.
        assigned_once = {}
        seen_multiple = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Assign):
                resolved = None
                if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                    resolved = n.value.value
                elif isinstance(n.value, ast.Call):
                    resolved = _resolve_join_call(n.value)
                if resolved is not None:
                    for target in n.targets:
                        if isinstance(target, ast.Name):
                            if target.id in assigned_once:
                                seen_multiple.add(target.id)
                            else:
                                assigned_once[target.id] = resolved
        self._string_constants = {k: v for k, v in assigned_once.items() if k not in seen_multiple}
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in self._DB_IMPORTS:
                self.db_signals.add(self._DB_IMPORTS[top])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            top = node.module.split(".")[0]
            if top in self._DB_IMPORTS:
                self.db_signals.add(self._DB_IMPORTS[top])
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        prev = self._current_handler_method
        if node.name in self._HANDLER_METHODS:
            self._current_handler_method = self._HANDLER_METHODS[node.name]
        # Decorator-based routing (Flask/FastAPI): @app.route("/x"),
        # @app.get("/x"), @router.post("/x"), etc. Scoped to decorators
        # specifically (not any arbitrary `.get(...)` call in the file —
        # that was a real false-positive bug: dict.get(), os.environ.get(),
        # self.headers.get() etc. all match `.attr == "get"` too) so only
        # genuine route registrations are counted.
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in self._HTTP_METHOD_NAMES | {"route"}
                    and dec.args and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                path_value = dec.args[0].value
                if dec.func.attr == "route":
                    # @app.route("/x", methods=["POST"]) declares its real verbs;
                    # without reading them a POST-only route was invisible to the
                    # body-fault experiments (they look for POST endpoints).
                    verbs = []
                    for kw in dec.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                            verbs = [el.value.upper() for el in kw.value.elts
                                     if isinstance(el, ast.Constant) and isinstance(el.value, str)]
                    for verb in (verbs or ["ROUTE"]):
                        self.endpoints.append({"method": verb, "path": path_value})
                else:
                    self.endpoints.append({"method": dec.func.attr.upper(), "path": path_value})
        self.generic_visit(node)
        self._current_handler_method = prev

    # FastAPI/async frameworks commonly declare handlers as `async def`;
    # ast.AsyncFunctionDef is a distinct node type from FunctionDef, so
    # without this alias every async route handler would be silently
    # invisible to the visitor above.
    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Compare(self, node):
        # `self.path == "/x"` / `parsed.path != "/y"` / `.path.startswith("/z")`
        # inside a do_GET/do_POST/... method body -> a real, literal endpoint.
        if self._current_handler_method:
            left_is_path = (
                (isinstance(node.left, ast.Attribute) and node.left.attr == "path")
                or (isinstance(node.left, ast.Name) and node.left.id.lower() in ("path", "pathname", "route", "url_path"))
            )
            if left_is_path and len(node.ops) == 1 and isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
                cmp = node.comparators[0]
                if isinstance(cmp, ast.Constant) and isinstance(cmp.value, str):
                    self.endpoints.append({"method": self._current_handler_method, "path": cmp.value})
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func

        if isinstance(func, ast.Attribute) and func.attr == "get":
            if isinstance(func.value, ast.Attribute) and func.value.attr == "environ":
                self._collect_env_arg(node)  # os.environ.get("X")
        if isinstance(func, ast.Attribute) and func.attr == "getenv":
            self._collect_env_arg(node)      # os.getenv("X")
        if isinstance(func, ast.Name) and func.id == "getenv":
            self._collect_env_arg(node)      # from os import getenv; getenv("X")

        if isinstance(func, ast.Name) and func.id == "open" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                self.filesystem_paths.add(arg.value)
            elif isinstance(arg, ast.Name) and arg.id in self._string_constants:
                self.filesystem_paths.add(self._string_constants[arg.id])
            elif isinstance(arg, ast.Call):
                inline_resolved = _resolve_join_call(arg)
                if inline_resolved:
                    self.filesystem_paths.add(inline_resolved)

        if isinstance(func, ast.Attribute) and func.attr in ("run", "call", "Popen", "check_output", "check_call"):
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                self.subprocess_calls += 1

        self.generic_visit(node)

    def visit_Subscript(self, node):
        if (isinstance(node.value, ast.Attribute) and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            self.env_vars.add(node.slice.value)  # os.environ["X"]
        self.generic_visit(node)

    def _collect_env_arg(self, call_node):
        if call_node.args and isinstance(call_node.args[0], ast.Constant) and isinstance(call_node.args[0].value, str):
            self.env_vars.add(call_node.args[0].value)
