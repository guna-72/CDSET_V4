from __future__ import annotations
"""
Chaos Tutor MVP — configuration & default safety limits.

This is the MVP_SAFE profile from the spec (section 19), scoped to the
limits this stdlib-only sandbox actually enforces. Every number here is a
hard ceiling used by app/safety_gate.py and app/sandbox.py — nothing in
the engine is allowed to exceed these without going through code review.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

DATA_DIR = os.path.join(BASE_DIR, "data")
STORAGE_DIR = os.path.join(DATA_DIR, "storage")       # original uploads (never modified)
WORKSPACE_DIR = os.path.join(DATA_DIR, "workspace")    # analysis / experiment copies
DB_PATH = os.environ.get("CHAOS_TUTOR_DB_PATH", os.path.join(DATA_DIR, "chaos_tutor.db"))

for d in (DATA_DIR, STORAGE_DIR, WORKSPACE_DIR):
    os.makedirs(d, exist_ok=True)

# ---- HTTP/API limits ----
# Must stay comfortably above MAX_ARCHIVE_BYTES below — the raw project
# upload is sent as the HTTP body itself (no multipart/chunking), so this
# is the real ceiling on how large an imported ZIP can be.
MAX_HTTP_REQUEST_BYTES = 600 * 1024 * 1024
MAX_JSON_BODY_BYTES = 256 * 1024
CORS_ALLOWED_ORIGINS = {x.strip() for x in os.environ.get("CHAOS_TUTOR_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()}
API_AUTH_TOKEN = os.environ.get("CHAOS_TUTOR_API_TOKEN", "").strip()
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_POSTS = 30

# ---- Upload limits ----
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024        # 500 MB
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024 # 2 GB
MAX_FILES = 50_000
MAX_SINGLE_FILE_BYTES = 200 * 1024 * 1024    # 200 MB
MAX_ARCHIVE_NESTING = 3
MAX_PATH_LEN = 255
MAX_FILENAME_LEN = 255

# Generated/dependency/VCS directories. Single source of truth shared by
# zip intake (app/intake.py), git intake (app/git_intake.py) and the
# per-experiment workspace copy (app/sandbox.py make_workspace) so they can
# never drift apart. ".git" is *kept* in storage for git-sourced projects
# (needed for "refresh from git") but is never copied into throwaway chaos
# workspaces, where the sandboxed process has no use for it.
IGNORED_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".venv", "venv", "env", "dist", "build", "target", ".idea", ".vscode",
    ".next", "coverage", "out", ".turbo", ".cache", "bower_components",
})

# Directories a throwaway chaos/IDE workspace copy leaves out. Deliberately
# much smaller than IGNORED_DIRS: dependency trees (node_modules, venv, ...)
# and build output (dist, build, ...) MUST be copied when a project has them,
# otherwise the sandboxed app dies at startup with "Cannot find module ...".
# Only VCS metadata and tool caches are never needed by the running process.
WORKSPACE_SKIP_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".mypy_cache"})

# ---- Git import limits ----
GIT_CLONE_TIMEOUT_SECONDS = 120
GIT_MAX_URL_LEN = 500

# ---- Sandbox limits (Windows has no POSIX rlimit API, so the wall-clock
# timeout below is the enforced ceiling on a sandboxed run's duration;
# there is no separate CPU/memory/process-count rlimit on this platform) ----
# Node/JVM services use a dozen-plus threads each; too many concurrent runs
# at once made them fail to start and produced false TARGET_UNREACHABLE
# results, so extra runs wait in line instead.
MAX_CONCURRENT_RUNS = max(1, int(os.environ.get("CHAOS_TUTOR_MAX_CONCURRENT_RUNS", "3")))
SANDBOX_WALL_TIMEOUT_SECONDS = 120  # hard wall-clock kill
SANDBOX_MAX_LOG_BYTES = 10 * 1024 * 1024
SANDBOX_MAX_LOG_LINE_BYTES = 64 * 1024

# ---- Experiment / concurrency limits ----
EXPERIMENT_TIMEOUT_LOW_RISK = 60
EXPERIMENT_TIMEOUT_NORMAL = 120
EXPERIMENT_TIMEOUT_COMPLEX = 300
EXPERIMENT_TIMEOUT_MAX = 300

MAX_ACTIVE_EXPERIMENTS_SYSTEM = 4
MAX_ACTIVE_EXPERIMENTS_USER = 1

# ---- Sandbox security policy ----
# Service-based chaos experiments ideally get OS-enforced network isolation
# (a Windows Firewall rule — see app/sandbox.py), which requires the backend
# to run elevated (as Administrator). Running elevated is not required to
# use the app: by default it runs in "degraded" mode (no network isolation,
# still workspace-isolated + fixed-argv) from any ordinary terminal. Set
# CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX=false to force strict isolation
# (requires launching the backend as Administrator).
def _degraded_sandbox_default(raw) -> bool:
    if raw is None or not str(raw).strip():
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


ALLOW_DEGRADED_SANDBOX = _degraded_sandbox_default(
    os.environ.get("CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX"))

# ---- Network policy ----
# This sandbox blocks *outbound* egress by clearing proxy env vars and
# refusing to pass through any HTTP(S)_PROXY / *_ADDR overrides. It does
# NOT use network namespaces (no CAP_NET_ADMIN available in this
# container), so it cannot stop a child process from opening raw sockets
# the way a real deployment (network namespace / iptables / Docker
# --network=none) would. This is a documented, honest gap — see
# KNOWN_LIMITATIONS in app/sandbox.py and the final report.
ALLOWED_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONUNBUFFERED"}

# Windows only: kernel/runtime plumbing that most Windows processes
# implicitly depend on to function at all, not just to run the target
# app's own logic. In particular, SystemRoot missing from a child
# process's environment is a well-known way to break Winsock
# initialization on Windows — which breaks *any* runtime's ability to
# open a listening socket (Node's libuv included), regardless of
# whether the target app's own code is correct. The base ALLOWED_ENV_KEYS
# above is sufficient on Linux (the whole test suite runs against it),
# but was silently insufficient for a Windows target to ever bind a
# port — indistinguishable from TARGET_UNREACHABLE at the harness level.
WINDOWS_ALLOWED_ENV_KEYS = {
    "SystemRoot", "SystemDrive", "windir", "TEMP", "TMP", "ComSpec",
    "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
}

# Operating system / platform environment variables that must never be treated
# as application configuration faults or clobbered with dummy values (e.g. setting
# SystemRoot="1" corrupts Winsock DLL resolution, causing WinError 10106).
SYSTEM_ENV_KEYS = {
    "PATH", "HOME", "LANG", "LC_ALL", "PYTHONUNBUFFERED",
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "COMSPEC",
    "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "USERNAME", "USER",
    "COMPUTERNAME", "LOGNAME", "PROMPT", "PSMODULEPATH", "OS",
    "ALLUSERSPROFILE", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
    "COMMONPROGRAMW6432", "HOMEDRIVE", "HOMEPATH", "LOGONSERVER",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "PUBLIC", "SESSIONNAME", "USERDOMAIN", "USERDOMAIN_ROAMINGPROFILE",
}

# ---- AI diagnosis ----
MAX_DIAGNOSIS_INPUT_BYTES = 100 * 1024
MAX_DIAGNOSIS_CANDIDATES = 20
