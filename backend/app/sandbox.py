from __future__ import annotations
"""
Sandbox — the primary security boundary (spec section 18/37).

Windows-only build. Real controls implemented here, no Docker required:
  - dedicated, isolated workspace directory per run (never the original upload)
  - subprocess with a FIXED executable + argument LIST (never shell=True,
    never string-built commands) -> command injection is structurally
    impossible from this module's call sites
  - wall-clock timeout, independent hard-kill of the process tree on expiry
  - stdout/stderr captured with byte caps
  - guaranteed cleanup (try/finally) even on crash/timeout
  - network isolation: a per-run Windows Firewall block rule (`netsh
    advfirewall firewall add rule ... program=<resolved executable>`)
    covering both inbound and outbound traffic for the exact
    interpreter/binary path used to launch the sandboxed process, added
    before start and removed on stop/crash. The rule is scoped to
    non-loopback remote addresses only (`remoteip=` excludes
    127.0.0.0/8), so the sandboxed process loses LAN/internet access but
    the harness on the same machine can still reach it over 127.0.0.1 to
    run readiness checks and send test traffic — an unscoped block takes
    down loopback too, which previously made every network-isolated
    service unreachable (TARGET_UNREACHABLE) regardless of whether the
    service was actually healthy. This requires the backend to be
    running elevated (Administrator) — `netsh advfirewall` rule changes
    are not permitted otherwise, so isolation silently reports
    unavailable without it and the sandbox falls back to
    privilege-drop-only isolation (degraded mode; see
    ALLOW_DEGRADED_SANDBOX in app/config.py, which defaults to enabled
    on Windows so the backend runs normally from any ordinary,
    non-elevated terminal).

Known gap: the firewall rule matches by executable *path*, not by
process/PID, so if the sandboxed project is launched via a shared
system interpreter (e.g. the system `python.exe` or `node.exe`) rather
than a binary living inside its own per-run workspace copy, the block
applies to every process using that same interpreter path for the
run's duration — documented here rather than silently overclaiming
per-process isolation.

Remaining known, documented gap: filesystem isolation is a plain
isolated directory, not a container/sandboxed filesystem jail — giving
every sandbox its own fully isolated filesystem is real future work,
not attempted this pass. There is no privilege drop on Windows (no
uid/gid model); the isolated workspace directory plus the fixed-argv
subprocess boundary plus the firewall-based network block are the
enforced controls.
"""
import functools
import json as _json
import os
try:
    import ctypes  # Windows admin check
except ImportError:
    ctypes = None
import shutil
import signal
import sys
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from app.longpath import lp
from dataclasses import dataclass, field

from app.config import (
    WORKSPACE_SKIP_DIRS,
    SANDBOX_WALL_TIMEOUT_SECONDS,
    SANDBOX_MAX_LOG_BYTES,
    WORKSPACE_DIR,
    ALLOWED_ENV_KEYS,
    WINDOWS_ALLOWED_ENV_KEYS,
    ALLOW_DEGRADED_SANDBOX,
)

PYTHON_EXECUTABLE = sys.executable

KNOWN_LIMITATIONS = [
    "Filesystem isolation is a plain isolated directory, not a "
    "container/jail — there is no per-run filesystem root, so a "
    "sandboxed process can still *read* any world-readable file on the "
    "host filesystem. There is no privilege drop on Windows (no "
    "uid/gid model); the isolated workspace directory, the fixed-argv "
    "subprocess boundary and the firewall-based network block are the "
    "enforced controls.",
    "No syscall filtering (e.g. seccomp) is applied — not available on "
    "Windows. The isolated workspace, fixed argv, and network/firewall "
    "isolation are the enforced controls instead.",
    "Network isolation is enforced via a Windows Firewall rule scoped "
    "to the sandboxed process's resolved executable path (and, within "
    "that, to non-loopback remote addresses only, so the harness can "
    "still reach the process over 127.0.0.1), not a true per-process "
    "kernel namespace. If that executable is a shared system "
    "interpreter (python.exe, node.exe) rather than a binary inside "
    "the run's own isolated workspace copy, the block applies to every "
    "process using that interpreter path for the duration of the run. "
    "The rule also does not follow process lineage: if the sandboxed "
    "process spawns a *different* executable as a child (e.g. shelling "
    "out to curl.exe, or another interpreter), that child's traffic is "
    "not blocked unless its own resolved path happens to already be "
    "covered by a rule. Also requires the backend to run elevated "
    "(Administrator); otherwise isolation reports unavailable and the "
    "sandbox falls back to degraded (privilege-drop-only, non-network- "
    "isolated) mode.",
]


class SandboxError(Exception):
    pass


_isolation_checked = False
_isolation_available = False
_isolation_lock = threading.Lock()


def _is_windows_admin() -> bool:
    """netsh advfirewall rule changes require an elevated process."""
    if ctypes is None:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _win_firewall_available() -> bool:
    if not _is_windows_admin():
        return False
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "show", "allprofiles", "state"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _windows() -> bool:
    return os.name == "nt"


def _resolve_executable(cmd: str) -> str | None:
    if os.path.isabs(cmd) and os.path.exists(cmd):
        return cmd
    return shutil.which(cmd)


def _win_fw_rule_names(rule_id: str) -> tuple[str, str]:
    return (f"ChaosTutorSandbox_{rule_id}_in", f"ChaosTutorSandbox_{rule_id}_out")


# Every IPv4 address except the loopback block (127.0.0.0/8), expressed as
# two ranges since netsh has no "all except" syntax. Scoping the block
# rules to this set (instead of remoteip=any) blocks the sandboxed
# process's access to the LAN/internet while leaving 127.0.0.1 traffic
# between the process and the harness alone — the harness's readiness
# probe and HTTP calls (wait_ready/probe_http, see below) both go over
# loopback, so a blanket remoteip=any block took them out along with the
# real target (outbound internet access).
_WIN_FW_NON_LOOPBACK = "0.0.0.0-126.255.255.255,128.0.0.0-255.255.255.255"


def _win_fw_block(program_path: str, rule_id: str) -> bool:
    """Add inbound + outbound block rules scoped to program_path, restricted
    to non-loopback remote addresses so the harness can still reach the
    sandboxed process over 127.0.0.1. Returns False (and leaves no rule
    behind) if either add fails, so callers never treat a half-applied
    block as real isolation."""
    name_in, name_out = _win_fw_rule_names(rule_id)
    try:
        r_in = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={name_in}", "dir=in", "action=block",
             f"program={program_path}", f"remoteip={_WIN_FW_NON_LOOPBACK}",
             "enable=yes"],
            capture_output=True, timeout=10,
        )
        r_out = subprocess.run(
            ["netsh", "advfirewall", "firewall", "add", "rule",
             f"name={name_out}", "dir=out", "action=block",
             f"program={program_path}", f"remoteip={_WIN_FW_NON_LOOPBACK}",
             "enable=yes"],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        _win_fw_unblock(rule_id)
        return False
    if r_in.returncode != 0 or r_out.returncode != 0:
        _win_fw_unblock(rule_id)
        return False
    return True


def _win_fw_unblock(rule_id: str) -> None:
    for name in _win_fw_rule_names(rule_id):
        try:
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"],
                capture_output=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def network_isolation_available() -> bool:
    """Return whether OS-enforced network isolation is usable: Windows
    Firewall rule support while running elevated (Administrator)."""
    if _isolation_checked:
        return _isolation_available
    with _isolation_lock:
        if _isolation_checked:
            return _isolation_available
        result = _win_firewall_available()
        _set_isolation_result(result)
        return result


def _set_isolation_result(result: bool) -> None:
    global _isolation_checked, _isolation_available
    _isolation_available = result
    _isolation_checked = True


def require_network_isolation() -> None:
    """Fail closed before starting an untrusted network-capable service.

    Degraded mode is opt-in for trusted local development only. It must never
    be silently selected because direct localhost networking can expose the
    host network to an uploaded project.
    """
    if not network_isolation_available() and not ALLOW_DEGRADED_SANDBOX:
        raise SandboxError(
            "OS-enforced network isolation is unavailable on this host; "
            "refusing to start a network-capable sandbox. Run the backend "
            "as Administrator so Windows Firewall rules can be applied, "
            "or explicitly set CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX=true for "
            "trusted local development only."
        )


@dataclass
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    workspace: str
    killed_reason: str | None = None
    net_isolated: bool = False


def _build_argv(real_argv: list[str]) -> tuple[list[str], bool, bool, str | None]:
    """Returns (argv_to_exec, will_be_net_isolated, is_node, fw_rule_id).

    fw_rule_id is set only when a firewall block rule was actually
    applied — the caller must pass it to _win_fw_unblock() once the
    process has stopped, or the rule is left behind.
    """
    is_node = bool(real_argv) and real_argv[0] == "node"
    is_jvm = bool(real_argv) and real_argv[0] in {"java", "javac", "kotlinc"}
    if is_node:
        # V8 reserves a large virtual address range before application code
        # runs; the heap cap is enforced at the runtime level instead.
        real_argv = [real_argv[0], "--max-old-space-size=256", *real_argv[1:]]
    elif is_jvm:
        if real_argv[0] in {"javac", "kotlinc"}:
            real_argv = [real_argv[0], "-J-Xmx256m", *real_argv[1:]]
        else:
            real_argv = [real_argv[0], "-Xmx256m", *real_argv[1:]]

    if _windows():
        # On Windows CreateProcess only appends ".exe", so a bare "npm"/"npx"
        # (really npm.cmd) raises FileNotFoundError and the Node Test button
        # could never start. shutil.which honours PATHEXT and returns the real
        # path; a full path to a .cmd/.bat is launched fine without a shell.
        resolved = _resolve_executable(real_argv[0])
        if resolved:
            real_argv = [resolved, *real_argv[1:]]

    if network_isolation_available():
        exe_path = _resolve_executable(real_argv[0])
        if exe_path:
            rule_id = uuid.uuid4().hex[:12]
            if _win_fw_block(exe_path, rule_id):
                return real_argv, True, is_node, rule_id
    return real_argv, False, is_node, None


def _inside_workspace(path: str) -> bool:
    root = os.path.realpath(WORKSPACE_DIR)
    candidate = os.path.realpath(path)
    return candidate == root or candidate.startswith(root + os.sep)


def make_workspace(source_dir: str, label: str) -> str:
    """Create an isolated copy of source_dir under WORKSPACE_DIR. Never
    touches source_dir itself (spec: original project is never modified)."""
    ws = os.path.join(WORKSPACE_DIR, f"{label}-{uuid.uuid4().hex[:12]}")
    # Skip only what the sandboxed process can never need: .git (present for
    # git-imported projects; large, and its read-only pack files are also
    # what makes rmtree fail on Windows) and tool caches. Dependency and build
    # directories are copied - an app cannot start without its node_modules.
    shutil.copytree(lp(source_dir), lp(ws), symlinks=False, ignore_dangling_symlinks=True,
                    ignore=shutil.ignore_patterns(*sorted(WORKSPACE_SKIP_DIRS)))
    return ws


def destroy_workspace(path: str):
    if not path or not _inside_workspace(path):
        raise SandboxError(f"refusing to destroy path outside workspace root: {path}")
    shutil.rmtree(lp(path), ignore_errors=True)


def _build_env(extra_env, cwd):
    keys = ALLOWED_ENV_KEYS | WINDOWS_ALLOWED_ENV_KEYS
    env = {k: os.environ[k] for k in keys if k in os.environ}
    # Prevent host-side Python/module injection from affecting sandbox startup.
    for _unsafe in (
        "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONHOME",
        "PYTHONUSERBASE", "PYTHONNOUSERSITE",
    ):
        env.pop(_unsafe, None)
    if extra_env:
        for k, v in extra_env.items():
            # extra_env is only ever populated by this codebase's own chaos
            # engine / recovery supervisor (app/chaos_engine.py,
            # app/recovery.py) — never taken directly from a network
            # request — so key *names* here come from a trusted call site,
            # even when a name (e.g. a project's own required env var) was
            # discovered by static analysis of untrusted project source.
            # The real risk is a name that overrides something the
            # interpreter/loader treats specially, so that's still blocked
            # unconditionally regardless of who's asking.
            if k in ("LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "NODE_OPTIONS"):
                continue
            # Windows: never allow extra_env to clobber core OS directories,
            # which breaks Winsock / DLL loading (WinError 10106).
            if k.upper() in {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT"}:
                continue
            env[k] = str(v)
    # Interpreter launchers such as pyenv/asdf shims, conda and ~/.local
    # installs locate the real binary through the user profile, so keep it.
    env.setdefault("HOME", cwd)
    # What the sandbox cannot do is *write* under that HOME, so send the
    # toolchain caches (go build cache, npm, XDG) to the disposable
    # workspace instead. Explicit values from extra_env still win.
    cache_root = os.path.join(cwd, ".chaos_cache")
    env.setdefault("XDG_CACHE_HOME", cache_root)
    env.setdefault("GOCACHE", os.path.join(cache_root, "go-build"))
    env.setdefault("npm_config_cache", os.path.join(cache_root, "npm"))
    env.pop("PYTHONSTARTUP", None)
    env.pop("PYTHONINSPECT", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_in_sandbox(
    argv: list[str],
    cwd: str,
    extra_env: dict | None = None,
    timeout: float = SANDBOX_WALL_TIMEOUT_SECONDS,
    stdin_data: str | None = None,
) -> SandboxResult:
    """Execute argv (a fixed list — never a shell string) inside cwd with
    all sandbox controls applied. This is the ONLY function in the
    codebase allowed to call subprocess against untrusted project code
    for a one-shot, run-to-completion command."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise SandboxError("argv must be a non-empty list of strings (no shell strings allowed)")
    if not _inside_workspace(cwd):
        raise SandboxError("sandbox execution is only allowed inside an isolated workspace copy")

    env = _build_env(extra_env, cwd)
    exec_argv, net_isolated, is_node, fw_rule_id = _build_argv(argv)

    start = time.time()
    timed_out = False
    killed_reason = None
    popen_kwargs = dict(
        cwd=cwd, env=env,
        stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    try:
        proc = subprocess.Popen(exec_argv, **popen_kwargs)
        try:
            stdout, stderr = proc.communicate(input=stdin_data, timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            killed_reason = f"wall-clock timeout after {timeout}s"
            _kill_process_group(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:
                stdout, stderr = "", ""
            exit_code = None
    finally:
        if fw_rule_id:
            _win_fw_unblock(fw_rule_id)
    duration = time.time() - start

    return SandboxResult(
        exit_code=exit_code,
        stdout=(stdout or "")[:SANDBOX_MAX_LOG_BYTES],
        stderr=(stderr or "")[:SANDBOX_MAX_LOG_BYTES],
        duration_seconds=duration,
        timed_out=timed_out,
        workspace=cwd,
        killed_reason=killed_reason,
        net_isolated=net_isolated,
    )


@dataclass
class ServiceHandle:
    proc: subprocess.Popen
    cwd: str
    stdout_path: str
    stderr_path: str
    net_isolated: bool = False
    started_at: float = field(default_factory=time.time)
    fw_rule_id: str | None = None  # Windows Firewall rule pending cleanup

    @property
    def pid(self) -> int:
        return self.proc.pid


def start_service(argv: list[str], cwd: str, extra_env: dict | None = None) -> ServiceHandle:
    """Start a long-running sandboxed process (e.g. an HTTP server under
    test) and return immediately with a handle. Same controls as
    run_in_sandbox but non-blocking, for chaos experiments that need to
    send it live traffic before shutting it down. Use wait_ready() /
    probe_http() below to talk to it."""
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise SandboxError("argv must be a non-empty list of strings (no shell strings allowed)")
    if not _inside_workspace(cwd):
        raise SandboxError("sandbox execution is only allowed inside an isolated workspace copy")

    env = _build_env(extra_env, cwd)
    env["PYTHONUNBUFFERED"] = "1"
    exec_argv, net_isolated, is_node, fw_rule_id = _build_argv(argv)

    stdout_path = os.path.join(cwd, ".chaos_sandbox_stdout.log")
    stderr_path = os.path.join(cwd, ".chaos_sandbox_stderr.log")
    stdout_f = open(stdout_path, "wb")
    stderr_f = open(stderr_path, "wb")

    popen_kwargs = dict(
        cwd=cwd, env=env,
        stdin=subprocess.DEVNULL, stdout=stdout_f, stderr=stderr_f,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    try:
        proc = subprocess.Popen(exec_argv, **popen_kwargs)
    except Exception:
        stdout_f.close()
        stderr_f.close()
        if fw_rule_id:
            _win_fw_unblock(fw_rule_id)
        raise
    stdout_f.close()
    stderr_f.close()
    return ServiceHandle(proc=proc, cwd=cwd, stdout_path=stdout_path, stderr_path=stderr_path,
                          net_isolated=net_isolated, fw_rule_id=fw_rule_id)


def stop_service(handle: ServiceHandle, grace_seconds: float = 1.0) -> SandboxResult:
    duration = time.time() - handle.started_at
    exit_code = handle.proc.poll()
    killed_reason = None
    if exit_code is None:
        try:
            handle.proc.terminate()
        except (ProcessLookupError, PermissionError, AttributeError):
            pass
        try:
            handle.proc.wait(timeout=grace_seconds)
            exit_code = handle.proc.returncode
            killed_reason = "terminated (graceful)"
        except subprocess.TimeoutExpired:
            _kill_process_group(handle.proc)
            try:
                handle.proc.wait(timeout=1.5)
            except Exception:
                pass
            exit_code = handle.proc.returncode
            killed_reason = "killed (did not exit after terminate)"
    if handle.fw_rule_id:
        _win_fw_unblock(handle.fw_rule_id)
        handle.fw_rule_id = None
    return SandboxResult(
        exit_code=exit_code,
        stdout=_read_capped(handle.stdout_path),
        stderr=_read_capped(handle.stderr_path),
        duration_seconds=duration,
        timed_out=False,
        workspace=handle.cwd,
        killed_reason=killed_reason,
        net_isolated=handle.net_isolated,
    )


def crash_service(handle: ServiceHandle, sig=getattr(signal, "SIGKILL", signal.SIGTERM)) -> None:
    try:
        handle.proc.kill()
    except (ProcessLookupError, PermissionError, AttributeError):
        pass
    # A killed process never reaches stop_service via _ensure_stopped()
    # (which only calls it while the process is still alive), so release
    # the firewall rule here too — otherwise it's leaked on every crash test.
    if handle.fw_rule_id:
        _win_fw_unblock(handle.fw_rule_id)
        handle.fw_rule_id = None


def service_is_alive(handle: ServiceHandle, grace_seconds: float = 0.3, poll_interval: float = 0.05) -> bool:
    """True if the sandboxed process is still running.

    Several experiments (malformed_request, request_burst, ...) inject a
    fault specifically to see whether it crashes the process. The client
    side observes the crash as a dropped/reset connection the instant the
    runtime tears the socket down - but the runtime still has to run its
    fatal-exception path and actually call exit() after that, which is not
    instantaneous. A single, immediate proc.poll() right after the failed
    request can therefore still see a process that is a few milliseconds
    from dying as "alive", turning a real CRASHED outcome into a lesser
    APPLICATION_FAILURE. Give it a short grace window to actually finish
    dying before concluding it's still up. When the process is already
    dead (the common case for a fault the app handles, and for a fault it
    fails on slowly) this returns immediately with no added delay.
    """
    if handle.proc.poll() is not None:
        return False
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        if handle.proc.poll() is not None:
            return False
    return True


# ------------------------------------------------------- network probing
# The only sanctioned way to talk to a sandboxed service. A sandboxed
# service on Windows always shares the harness's own loopback (the
# firewall rule only blocks non-loopback remote addresses), so a direct
# loopback connection is always correct here.

def wait_ready(handle: ServiceHandle, port: int, timeout: float = 8.0, cancel_check=None) -> bool:
    return _wait_ready_direct(port, timeout, cancel_check=cancel_check)


def probe_http(handle: ServiceHandle, port: int, path: str, method: str = "GET",
                data: bytes | None = None, headers: dict | None = None,
                timeout: float = 3.0) -> dict:
    return _http_call_direct(port, path, method, data, headers, timeout)


def probe_http_direct(port: int, path: str, method: str = "GET", data: bytes | None = None,
                       headers: dict | None = None, timeout: float = 3.0) -> dict:
    """Public, explicit bypass — kept for the two call sites (post-stop
    connection_refused check, post-kill process_kill check) where the
    sandboxed process is already dead or about to be."""
    return _http_call_direct(port, path, method, data, headers, timeout)


def _wait_ready_direct(port: int, timeout: float, cancel_check=None) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_check and cancel_check():
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            if cancel_check and cancel_check():
                return False
            time.sleep(0.05)
    return False


class _LoopbackOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """The direct probe runs in the harness process (host network), so a target
    that answers 302 -> http://internal-host/ must not be able to steer the
    harness there. Only redirects that stay on loopback are followed; anything
    else surfaces as the 3xx response itself."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        host = (urlparse(newurl).hostname or "").lower()
        if host not in ("127.0.0.1", "localhost", "::1", ""):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _http_call_direct(port, path, method, data, headers, timeout) -> dict:
    path = path if str(path).startswith("/") else f"/{path}"
    url = f"http://127.0.0.1:{port}{path}"
    start = time.time()
    try:
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        opener = urllib.request.build_opener(_LoopbackOnlyRedirect)
        with opener.open(req, timeout=timeout) as r:
            body = r.read(65536)
            return {"ok": True, "status": r.status, "body": body.decode("utf-8", "ignore")[:2000],
                    "latency_ms": round((time.time() - start) * 1000, 1)}
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        return {"ok": True, "status": e.code, "body": body[:2000].decode("utf-8", "ignore"),
                "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "latency_ms": round((time.time() - start) * 1000, 1)}


def _read_capped(path, cap=SANDBOX_MAX_LOG_BYTES):
    try:
        with open(path, "rb") as f:
            data = f.read(cap)
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def kill_pid_tree(pid: int, sig=getattr(signal, "SIGKILL", signal.SIGTERM)):
    try:
        os.kill(pid, sig)
    except (OSError, ProcessLookupError):
        pass


def _kill_process_group(proc: subprocess.Popen):
    try:
        proc.kill()
    except OSError:
        pass
