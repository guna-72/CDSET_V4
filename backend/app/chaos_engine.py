from __future__ import annotations
"""
Chaos Engine (spec section 21/12) + Execution Engine.

Takes ONE safety-gate-approved experiment and actually runs it: spins up
an isolated sandbox copy (never the original), launches the real target
process inside it (in its own network namespace when the host supports
it — see app/sandbox.py), injects the fault, and captures real
observations via app.sandbox.wait_ready / app.sandbox.probe_http, which
route through nsenter for isolated services. Every function here does
genuine work — no hardcoded results (spec section 4/Rule 4).

Note on "missing_env_var" never targeting PORT: this harness uses its
own PORT env var to control which port it polls for readiness, so
removing PORT would be indistinguishable from the harness's own plumbing
rather than a real app-config fault — app/experiment_generator.py
excludes it for that reason.
"""
import json
import os
import socket
import time
import sys
import threading

from app import sandbox, recovery
from app.config import SYSTEM_ENV_KEYS

READY_TIMEOUT = 8
REQUEST_TIMEOUT = 3
OVERSIZED_PAYLOAD_BYTES = 2 * 1024 * 1024  # 2MB — well under the MVP_SAFE single-file cap
BURST_CONCURRENCY = 20                      # spec section 19: "Concurrent requests: 10" bucket-adjacent, bounded


_run_context = threading.local()

def _cancel_requested():
    run_id = getattr(_run_context, "run_id", None)
    if not run_id:
        return False
    from app import orchestrator
    return orchestrator.is_cancel_requested(run_id)

def _check_cancel():
    if _cancel_requested():
        raise RuntimeError("CANCEL_REQUESTED: operator asked CD-SET to stop this test")

def _register_handle(handle):
    run_id = getattr(_run_context, "run_id", None)
    if run_id and handle:
        from app import orchestrator
        orchestrator.register_active_handle(run_id, handle)
    return handle

def _unregister_handle(handle):
    run_id = getattr(_run_context, "run_id", None)
    if run_id and handle:
        from app import orchestrator
        orchestrator.unregister_active_handle(run_id, handle)
    return handle

def execute_experiment(experiment: dict, project_dir: str, profile: dict, run_id: str | None = None) -> dict:
    _run_context.run_id = run_id
    _check_cancel()
    fault_type = experiment["fault_type"]
    handlers = {
        "malformed_request": lambda: _fault_http_request(experiment, project_dir, profile, "malformed_request"),
        "empty_input": lambda: _fault_http_request(experiment, project_dir, profile, "empty_input"),
        "oversized_payload": lambda: _fault_http_request(experiment, project_dir, profile, "oversized_payload"),
        "boundary_input": lambda: _fault_http_request(experiment, project_dir, profile, "boundary_input"),
        "invalid_content_type": lambda: _fault_http_request(experiment, project_dir, profile, "invalid_content_type"),
        "wrong_http_method": lambda: _fault_http_request(experiment, project_dir, profile, "wrong_http_method"),
        "null_json_body": lambda: _fault_http_request(experiment, project_dir, profile, "null_json_body"),
        "special_characters": lambda: _fault_http_request(experiment, project_dir, profile, "special_characters"),
        "long_url": lambda: _fault_http_request(experiment, project_dir, profile, "long_url"),
        "unknown_route": lambda: _fault_http_request(experiment, project_dir, profile, "unknown_route"),
        "deeply_nested_json": lambda: _fault_http_request(experiment, project_dir, profile, "deeply_nested_json"),
        "request_burst": lambda: _fault_request_burst(experiment, project_dir, profile),
        "connection_refused": lambda: _fault_connection_refused(experiment, project_dir, profile),
        "slow_response": lambda: _fault_slow_response(experiment, project_dir, profile),
        "process_kill": lambda: _fault_process_kill(experiment, project_dir, profile),
        "process_kill_recovery": lambda: _fault_process_kill_recovery(experiment, project_dir, profile),
        "missing_env_var": lambda: _fault_missing_env_var(experiment, project_dir, profile),
        "missing_file": lambda: _fault_missing_file(experiment, project_dir, profile),
        "permission_denied": lambda: _fault_permission_denied(experiment, project_dir, profile),
        "db_connection_refused": lambda: _fault_db_connection_refused(experiment, project_dir, profile),
    }
    if fault_type not in handlers:
        raise ValueError(f"no chaos engine handler for fault_type '{fault_type}'")
    try:
        return handlers[fault_type]()
    finally:
        _run_context.run_id = None


# ---------------------------------------------------------------- helpers

def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class CompileError(Exception):
    """A deterministic-CLI adapter's build step failed. This is a defect in
    the uploaded project's own code (or its toolchain being genuinely
    absent), never a sandbox security refusal — kept as its own exception
    type so it isn't confused with SandboxError (a capability/policy
    refusal) by orchestrator.py's error handling, and so the run is
    recorded as FAILED with the compiler's own message rather than as
    BLOCKED by security policy."""


# Deterministic-CLI adapters that need a build step before they can be
# launched. Each entry returns the compile argv for a given entrypoint
# filename; None here (Go/PHP/Ruby, and every Python/Node adapter) means
# "runs directly, no separate compile step" (see _launch_argv below).
_CLI_BUILD_OUTPUT = "chaos_cli_target"  # stable, cwd-relative — never an absolute path


def _compile_argv(adapter: str, entry: str) -> list[str] | None:
    if adapter == "java_cli":
        return ["javac", entry]
    if adapter == "cpp_cli":
        return ["g++", entry, "-o", _CLI_BUILD_OUTPUT]
    if adapter == "c_cli":
        return ["gcc", entry, "-o", _CLI_BUILD_OUTPUT]
    if adapter == "rust_cli":
        return ["rustc", entry, "-o", _CLI_BUILD_OUTPUT]
    if adapter == "kotlin_cli":
        return ["kotlinc", entry, "-include-runtime", "-d", f"{_CLI_BUILD_OUTPUT}.jar"]
    return None


def _compile_if_needed(profile: dict, ws: str) -> None:
    """Builds the project's chosen entrypoint inside this specific sandbox
    workspace copy before it's started — a no-op for every adapter that
    doesn't need a separate build step. Must be called once per workspace
    (baseline and chaos copies are independent extracted copies of the
    same source, so each needs its own build), before _launch_argv's
    returned command is executed against that workspace."""
    adapter = profile.get("adapter")
    entry = profile.get("entrypoint")
    compile_argv = _compile_argv(adapter, entry) if entry else None
    if compile_argv is None:
        return
    # Defense in depth: orchestrator.py already refuses to run any experiment
    # against a project analyzer.py marked anything other than SUPPORTED
    # (which includes "compiler missing" — see analyzer.py's
    # _missing_toolchain), so this should never actually fire in the normal
    # flow. Still handled explicitly rather than left to crash if it's ever
    # reached some other way (e.g. the toolchain was removed after analysis).
    try:
        result = sandbox.run_in_sandbox(compile_argv, cwd=ws)
    except FileNotFoundError as e:
        raise CompileError(f"{compile_argv[0]} is not available in this environment: {e}") from e
    if result.timed_out or result.exit_code != 0:
        reason = "timed out" if result.timed_out else f"exited {result.exit_code}"
        raise CompileError(
            f"{compile_argv[0]} failed to build {entry} ({reason}): "
            f"{(result.stderr or result.stdout or '').strip()[:2000]}"
        )


def _launch_argv(profile: dict):
    """The command to execute for this project's adapter, or None if the
    adapter has no execution path at all. For the adapters _compile_argv
    handles (java_cli/cpp_cli/c_cli/rust_cli/kotlin_cli) this is the
    POST-build run command — the caller must call _compile_if_needed(profile,
    ws) against the SAME workspace first, or the build artifact this
    references won't exist yet."""
    adapter = profile.get("adapter")
    entry = profile.get("entrypoint")
    if not entry:
        return None
    if adapter in ("python_generic_http", "python_generic_cli", "python_flask", "python_fastapi"):
        return [sys.executable, entry]
    if adapter in ("node_generic", "node_express"):
        return ["node", entry]
    if adapter == "go_cli":
        return ["go", "run", entry]  # `go run` builds+runs in one step, no separate compile needed
    if adapter == "php_cli":
        return ["php", entry]
    if adapter == "ruby_cli":
        return ["ruby", entry]
    if adapter == "java_cli":
        return ["java", os.path.splitext(os.path.basename(entry))[0]]
    if adapter in ("cpp_cli", "c_cli", "rust_cli"):
        return [f"./{_CLI_BUILD_OUTPUT}"]
    if adapter == "kotlin_cli":
        return ["java", "-jar", f"{_CLI_BUILD_OUTPUT}.jar"]
    return None


def _env_defaults(profile: dict, exclude: str | None = None) -> dict:
    """Chaos experiments other than 'missing_env_var' aren't testing env-var
    handling — they need the target service to actually boot so the fault
    under test can be observed. A project can require startup env vars
    beyond PORT (an API key, a secret, etc.); without a safe placeholder
    for those, the service exits before the experiment even begins and
    every outcome collapses into an uninformative TARGET_UNREACHABLE,
    regardless of the fault being tested. `exclude` lets the
    missing_env_var experiment still omit the one var it's deliberately
    testing."""
    names = (profile.get("components") or {}).get("env_vars") or []
    ex = (exclude or "").upper()
    return {
        name: "1"
        for name in names
        if name != "PORT" and name.upper() not in SYSTEM_ENV_KEYS and name.upper() != ex
    }


def _ensure_stopped(handle):
    _unregister_handle(handle)
    try:
        if handle is not None and sandbox.service_is_alive(handle):
            sandbox.stop_service(handle, grace_seconds=0.1 if _cancel_requested() else 1.0)
    except Exception:
        pass


def _start_and_wait(argv, ws, port, profile=None, exclude_env=None):
    _check_cancel()
    # Service experiments execute untrusted project code that can open sockets.
    # Never silently fall back to host networking.
    sandbox.require_network_isolation()
    if profile:
        _compile_if_needed(profile, ws)  # no-op for adapters that don't need a build step
    _check_cancel()
    extra_env = {"PORT": str(port)}
    if profile:
        extra_env.update(_env_defaults(profile, exclude=exclude_env))
    handle = _register_handle(sandbox.start_service(argv, cwd=ws, extra_env=extra_env))
    ready = sandbox.wait_ready(handle, port, timeout=READY_TIMEOUT, cancel_check=_cancel_requested)
    _check_cancel()
    return handle, ready


# ------------------------------------------------------------- fault handlers

def _fault_http_request(experiment, project_dir, profile, mode):
    paths = experiment["parameters"].get("candidate_paths") or ["/"]
    target_path = paths[0]
    ws = sandbox.make_workspace(project_dir, "chaos")
    argv = _launch_argv(profile)
    port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, port, profile=profile)
        if not ready:
            stop = sandbox.stop_service(handle)
            handle = None
            return {"baseline": None, "chaos": None, "service_ready": False,
                    "stdout": stop.stdout, "stderr": stop.stderr, "exit_code": stop.exit_code,
                    "events": [{"type": "SYSTEM", "message": "service never became ready; see stderr"}]}

        _check_cancel()
        baseline = sandbox.probe_http(handle, port, "/")
        events = [{"type": "INJECTED_FAULT", "message": f"sending {mode} to {target_path}"}]

        _check_cancel()
        if mode == "malformed_request":
            chaos = sandbox.probe_http(handle, port, target_path, "POST", b"{not valid json",
                                        {"Content-Type": "application/json"})
        elif mode == "empty_input":
            chaos = sandbox.probe_http(handle, port, target_path, "POST", b"",
                                        {"Content-Type": "application/json"})
        elif mode == "oversized_payload":
            chaos = sandbox.probe_http(handle, port, target_path, "POST", b"x" * OVERSIZED_PAYLOAD_BYTES,
                                        {"Content-Type": "application/octet-stream"})
        elif mode == "invalid_content_type":
            payload = json.dumps({"title": "valid json, wrong header"}).encode()
            chaos = sandbox.probe_http(handle, port, target_path, "POST", payload,
                                        {"Content-Type": "application/xml"})
        elif mode == "wrong_http_method":
            chaos = sandbox.probe_http(handle, port, target_path, "PUT", b'{"title": "x"}',
                                        {"Content-Type": "application/json"})
        elif mode == "null_json_body":
            chaos = sandbox.probe_http(handle, port, target_path, "POST", b"null",
                                        {"Content-Type": "application/json"})
        elif mode == "special_characters":
            payload = json.dumps({"title": "O'Brien \"quoted\" <b>bold</b> 'OR'1'='1 \u2603 \U0001F600 \u0000 caf\u00e9",
                                  "name": "\u202e\ufeff%s%n{{7*7}}"}).encode()
            chaos = sandbox.probe_http(handle, port, target_path, "POST", payload,
                                        {"Content-Type": "application/json"})
        elif mode == "long_url":
            sep = "&" if "?" in target_path else "?"
            chaos = sandbox.probe_http(handle, port, target_path + sep + "q=" + "a" * 8000, "GET")
        elif mode == "unknown_route":
            chaos = sandbox.probe_http(handle, port, "/__chaos_no_such_page__", "GET")
        elif mode == "deeply_nested_json":
            depth = 3000
            payload = ("[" * depth + "]" * depth).encode()
            chaos = sandbox.probe_http(handle, port, target_path, "POST", payload,
                                        {"Content-Type": "application/json"})
        else:  # boundary_input
            payload = json.dumps({"title": 12345, "unexpected_field": [1, 2, 3] * 100}).encode()
            chaos = sandbox.probe_http(handle, port, target_path, "POST", payload,
                                        {"Content-Type": "application/json"})

        _check_cancel()
        still_alive = sandbox.service_is_alive(handle)
        post_fault_check = sandbox.probe_http(handle, port, "/") if still_alive else {"ok": False, "error": "process not alive"}
        _check_cancel()
        stop = sandbox.stop_service(handle)
        handle = None
        return {
            "baseline": baseline, "chaos": chaos, "post_fault_check": post_fault_check,
            "service_alive_after_fault": still_alive, "service_ready": True,
            "stdout": stop.stdout, "stderr": stop.stderr, "exit_code": stop.exit_code,
            "events": events,
        }
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _fault_request_burst(experiment, project_dir, profile):
    """New: fires BURST_CONCURRENCY concurrent requests at the target
    (spec section 12's HTTP 429 / concurrency category) and reports how
    many succeeded, errored, or came back 429/5xx — genuine concurrent
    load via a real thread pool, each request a real nsenter-routed probe
    when the service is network-isolated."""
    import concurrent.futures
    paths = experiment["parameters"].get("candidate_paths") or ["/"]
    target_path = paths[0]
    ws = sandbox.make_workspace(project_dir, "chaos")
    argv = _launch_argv(profile)
    port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, port, profile=profile)
        if not ready:
            stop = sandbox.stop_service(handle)
            handle = None
            return {"baseline": None, "chaos": None, "service_ready": False,
                    "stdout": stop.stdout, "stderr": stop.stderr, "exit_code": stop.exit_code, "events": []}

        baseline = sandbox.probe_http(handle, port, target_path)
        events = [{"type": "INJECTED_FAULT",
                   "message": f"firing {BURST_CONCURRENCY} concurrent requests at {target_path}"}]

        _check_cancel()
        with concurrent.futures.ThreadPoolExecutor(max_workers=BURST_CONCURRENCY) as pool:
            futures = [pool.submit(sandbox.probe_http, handle, port, target_path, "GET", None, None, 5)
                       for _ in range(BURST_CONCURRENCY)]
            results = []
            for f in futures:
                if _cancel_requested():
                    pool.shutdown(wait=False, cancel_futures=True)
                    _check_cancel()
                results.append(f.result(timeout=5))

        _check_cancel()
        still_alive = sandbox.service_is_alive(handle)
        _check_cancel()
        stop = sandbox.stop_service(handle)
        handle = None

        statuses = [r.get("status") for r in results if r.get("ok")]
        errors = [r for r in results if not r.get("ok")]
        return {
            "baseline": baseline,
            "chaos": {
                "total_sent": BURST_CONCURRENCY, "succeeded": len(statuses),
                "connection_errors": len(errors), "status_counts": _count(statuses),
                "any_429": 429 in statuses, "any_5xx": any(s >= 500 for s in statuses if s),
            },
            "service_alive_after_fault": still_alive, "service_ready": True,
            "exit_code": stop.exit_code, "events": events,
        }
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _fault_connection_refused(experiment, project_dir, profile):
    paths = experiment["parameters"].get("candidate_paths") or ["/"]
    target_path = paths[0]
    ws = sandbox.make_workspace(project_dir, "chaos")
    argv = _launch_argv(profile)
    port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, port, profile=profile)
        baseline = sandbox.probe_http(handle, port, target_path) if ready else {"ok": False, "error": "service never became ready"}
        stop = sandbox.stop_service(handle)
        handle = None
        events = [{"type": "INJECTED_FAULT", "message": "service stopped; probing while unreachable"}]
        chaos = sandbox.probe_http_direct(port, target_path, "GET", None, None, 2)
        return {"baseline": baseline, "chaos": chaos, "service_ready": bool(ready),
                "exit_code": stop.exit_code, "events": events}
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _fault_slow_response(experiment, project_dir, profile):
    paths = experiment["parameters"].get("candidate_paths") or ["/"]
    ws = sandbox.make_workspace(project_dir, "chaos")
    argv = _launch_argv(profile)
    port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, port, profile=profile)
        if not ready:
            stop = sandbox.stop_service(handle)
            handle = None
            return {"baseline": None, "chaos": None, "service_ready": False,
                    "stdout": stop.stdout, "stderr": stop.stderr, "events": []}
        baseline = sandbox.probe_http(handle, port, "/")
        events = [{"type": "INJECTED_FAULT",
                   "message": f"probing {paths} with a tight {REQUEST_TIMEOUT}s client timeout"}]
        results = []
        for p in paths:
            _check_cancel()
            results.append(sandbox.probe_http(handle, port, p, timeout=REQUEST_TIMEOUT))
        stop = sandbox.stop_service(handle)
        handle = None
        any_timeout = any((not r["ok"] and "timed out" in str(r.get("error") or "").lower()) for r in results)
        return {"baseline": baseline, "chaos": {"probed": results, "any_timeout_detected": any_timeout},
                "service_ready": True, "exit_code": stop.exit_code, "events": events}
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _fault_process_kill(experiment, project_dir, profile):
    ws = sandbox.make_workspace(project_dir, "chaos")
    argv = _launch_argv(profile)
    port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, port, profile=profile)
        baseline = sandbox.probe_http(handle, port, "/") if ready else {"ok": False, "error": "service never became ready"}
        events = [{"type": "INJECTED_FAULT", "message": "SIGKILL sent to process mid-run"}]
        if not ready:
            events.insert(0, {"type": "SYSTEM", "message": "service never became ready before the fault; "
                              "the process-kill result is inconclusive"})
        sandbox.crash_service(handle)
        time.sleep(0.5)
        alive = sandbox.service_is_alive(handle)
        chaos = sandbox.probe_http_direct(port, "/", "GET", None, None, 2)  # process is dead; no ns left to nsenter into
        exit_code = handle.proc.poll()
        return {"baseline": baseline, "chaos": chaos, "process_alive_after_kill": alive,
                "service_ready": bool(ready), "exit_code": exit_code, "events": events}
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _fault_process_kill_recovery(experiment, project_dir, profile):
    """New (spec section 24, P1): wraps the target in a real
    recovery.SupervisedService, kills it, and measures whether/how fast a
    simple restart-on-crash supervisor brings it back to a working state.
    This is genuine process supervision, not a simulated recovery."""
    # Same fail-closed isolation policy as every other service experiment.
    sandbox.require_network_isolation()
    ws = sandbox.make_workspace(project_dir, "chaos")
    argv = _launch_argv(profile)
    port = _free_port()
    sup = None
    try:
        _check_cancel()
        _compile_if_needed(profile, ws)
        _check_cancel()
        sup = _register_handle(recovery.SupervisedService(argv, cwd=ws, extra_env={"PORT": str(port), **_env_defaults(profile)}, max_restarts=2))
        old_handle = _register_handle(sup.current_handle())
        ready = sandbox.wait_ready(old_handle, port, timeout=READY_TIMEOUT, cancel_check=_cancel_requested)
        _check_cancel()
        baseline = sandbox.probe_http(old_handle, port, "/") if ready else {"ok": False, "error": "service never became ready"}
        events = [{"type": "INJECTED_FAULT", "message": "SIGKILL sent to supervised process"}]

        sandbox.crash_service(old_handle)
        _unregister_handle(old_handle)
        _check_cancel()
        new_handle = sup.wait_for_new_handle(old_handle, timeout=6, cancel_check=_cancel_requested)
        _check_cancel()
        recovered = False
        post_recovery = {"ok": False, "error": "supervisor did not restart the process in time"}
        if new_handle is not None:
            _register_handle(new_handle)
            recovered = sandbox.wait_ready(new_handle, port, timeout=4, cancel_check=_cancel_requested)
            _check_cancel()
            if recovered:
                post_recovery = sandbox.probe_http(new_handle, port, "/")

        return {
            "baseline": baseline, "chaos": post_recovery, "recovered": recovered,
            "service_ready": bool(ready),
            "restart_events": sup.restart_events, "events": events,
        }
    finally:
        if sup is not None:
            _unregister_handle(sup)
            sup.stop()
        sandbox.destroy_workspace(ws)


def _fault_missing_env_var(experiment, project_dir, profile):
    var = experiment["parameters"]["env_var"]
    argv = _launch_argv(profile)
    # This handler starts services directly (not via _start_and_wait), so it
    # must enforce the same fail-closed isolation policy itself.
    sandbox.require_network_isolation()

    ws_b = sandbox.make_workspace(project_dir, "baseline")
    port_b = _free_port()
    handle_b = None
    try:
        _check_cancel()
        _compile_if_needed(profile, ws_b)
        _check_cancel()
        handle_b = _register_handle(sandbox.start_service(argv, cwd=ws_b, extra_env={"PORT": str(port_b), var: "1", **_env_defaults(profile, exclude=var)}))
        ready_b = sandbox.wait_ready(handle_b, port_b, timeout=READY_TIMEOUT, cancel_check=_cancel_requested)
        _check_cancel()
        baseline = sandbox.probe_http(handle_b, port_b, "/") if ready_b else {"ok": False, "error": "service never became ready"}
        sandbox.stop_service(handle_b)
        _unregister_handle(handle_b)
        handle_b = None
    finally:
        _ensure_stopped(handle_b)
        sandbox.destroy_workspace(ws_b)

    _check_cancel()
    ws_c = sandbox.make_workspace(project_dir, "chaos")
    port_c = _free_port()
    handle_c = None
    try:
        _check_cancel()
        _compile_if_needed(profile, ws_c)
        _check_cancel()
        handle_c = _register_handle(sandbox.start_service(argv, cwd=ws_c, extra_env={"PORT": str(port_c), **_env_defaults(profile, exclude=var)}))  # var intentionally absent
        ready_c = sandbox.wait_ready(handle_c, port_c, timeout=READY_TIMEOUT, cancel_check=_cancel_requested)
        _check_cancel()
        chaos = sandbox.probe_http(handle_c, port_c, "/") if ready_c else {"ok": False, "error": "service never became ready"}
        _check_cancel()
        stop_c = sandbox.stop_service(handle_c)
        _unregister_handle(handle_c)
        handle_c = None
        events = [{"type": "INJECTED_FAULT", "message": f"started service with {var} unset"}]
        return {"baseline": baseline, "chaos": chaos, "chaos_service_ready": ready_c,
                "service_ready": bool(ready_c),
                "stdout": stop_c.stdout, "stderr": stop_c.stderr, "exit_code": stop_c.exit_code,
                "events": events}
    finally:
        _ensure_stopped(handle_c)
        sandbox.destroy_workspace(ws_c)


def _fault_missing_file(experiment, project_dir, profile):
    rel = experiment["parameters"]["relative_path"]
    ws = sandbox.make_workspace(project_dir, "chaos")
    target_file = os.path.join(ws, rel)
    events = []
    if os.path.exists(target_file):
        os.remove(target_file)
        events.append({"type": "INJECTED_FAULT", "message": f"removed {rel} from the sandbox copy"})
    else:
        events.append({"type": "SYSTEM", "message": f"{rel} was already absent in the extracted copy"})

    argv = _launch_argv(profile)
    port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, port, profile=profile)
        _check_cancel()
        chaos = sandbox.probe_http(handle, port, "/") if ready else None
        _check_cancel()
        stop = sandbox.stop_service(handle)
        handle = None
        return {"baseline": None, "chaos": chaos, "service_ready": ready,
                "stdout": stop.stdout, "stderr": stop.stderr, "exit_code": stop.exit_code,
                "events": events}
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _deny_all_access(target_file: str) -> str:
    """Best-effort, platform-correct read-denial on target_file.

    os.chmod() is not enough on its own: on Windows, CPython's chmod()
    only ever toggles the read-only *attribute* (removes the write bit) -
    every other bit, including the ones that would block reads, is
    silently ignored (this is documented CPython behavior, not a bug in
    Python itself). A file "chmod 000"'d that way is still perfectly
    readable, so on the one platform this build actually ships for, the
    permission_denied experiment would never produce a real permission
    error for a file the app only reads - it would just always report
    the fault as harmless, regardless of whether the app handles a real
    permission error at all. Use icacls, the real Windows ACL tool, to
    add an explicit Deny entry for the current user instead; fall back to
    chmod (correct on POSIX, and better than nothing elsewhere) if icacls
    isn't available or fails for any reason. Returns a short human-
    readable description of what was actually applied, for the run's
    event log.
        """
    if os.name == "nt":
        try:
            import subprocess as _subprocess
            user = os.environ.get("USERNAME")
            if user:
                result = _subprocess.run(
                    ["icacls", target_file, "/deny", f"{user}:(R,W)"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    return "denied via icacls ACL (real read/write denial)"
        except Exception:
            pass
        # icacls unavailable/failed — fall through to chmod, which on
        # Windows only strips the read-only attribute; document that.
        os.chmod(target_file, 0o000)
        return "marked read-only via os.chmod (icacls unavailable — this does not block reads on Windows)"
    os.chmod(target_file, 0o000)
    return "revoked all permissions via chmod 000 (no effect for a process running as root)" if os.geteuid() == 0 else "revoked all permissions via chmod 000"


def _fault_permission_denied(experiment, project_dir, profile):
    rel = experiment["parameters"]["relative_path"]
    ws = sandbox.make_workspace(project_dir, "chaos")
    target_file = os.path.join(ws, rel)
    events = []
    if os.path.exists(target_file):
        detail = _deny_all_access(target_file)
        events.append({"type": "INJECTED_FAULT", "message": f"{detail} on {rel}"})
    else:
        events.append({"type": "SYSTEM", "message": f"{rel} not found in the extracted copy"})

    argv = _launch_argv(profile)
    port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, port, profile=profile)
        _check_cancel()
        chaos = sandbox.probe_http(handle, port, "/") if ready else None
        _check_cancel()
        stop = sandbox.stop_service(handle)
        handle = None
        return {"baseline": None, "chaos": chaos, "service_ready": ready,
                "stdout": stop.stdout, "stderr": stop.stderr, "exit_code": stop.exit_code,
                "events": events}
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _fault_db_connection_refused(experiment, project_dir, profile):
    """Only ever generated when analyzer detected a real DB import/signal.
    No real DB runs in this sandbox, so the honest experiment is: start
    the app, and confirm the conventional port for the detected engine is
    unreachable — which, now that services run in their own isolated
    network namespace, is true for a much stronger reason than before
    (the sandbox has NO route to anything but its own loopback, not just
    'no DB happens to be running')."""
    db_ports = {"PostgreSQL": 5432, "MySQL": 3306, "MongoDB": 27017, "Redis": 6379}
    target = experiment["target"]
    engine = target.split(":", 1)[1] if ":" in target else None
    probe_port = db_ports.get(engine, 5432)

    ws = sandbox.make_workspace(project_dir, "chaos")
    argv = _launch_argv(profile)
    app_port = _free_port()
    handle = None
    try:
        _check_cancel()
        handle, ready = _start_and_wait(argv, ws, app_port, profile=profile)
        _check_cancel()
        baseline = sandbox.probe_http(handle, app_port, "/") if ready else {"ok": False, "error": "service never became ready"}
        _check_cancel()
        if handle.net_isolated:
            # ask the sandbox's OWN namespace whether it can reach the DB port —
            # this is the scenario that actually matters
            db_reachable = sandbox.wait_ready(handle, probe_port, timeout=1, cancel_check=_cancel_requested)
        else:
            try:
                with socket.create_connection(("127.0.0.1", probe_port), timeout=1):
                    db_reachable = True
            except OSError:
                db_reachable = False
        _check_cancel()
        stop = sandbox.stop_service(handle)
        was_isolated = handle.net_isolated
        handle = None
        events = [{"type": "INJECTED_FAULT",
                   "message": f"probed conventional {engine} port {probe_port} from the sandbox's own network view "
                              f"(isolated={was_isolated})"}]
        return {"baseline": baseline, "chaos": {"db_port_reachable": db_reachable, "engine": engine},
                "service_ready": bool(ready), "exit_code": stop.exit_code, "events": events}
    finally:
        _ensure_stopped(handle)
        sandbox.destroy_workspace(ws)


def _count(items):
    out = {}
    for i in items:
        out[str(i)] = out.get(str(i), 0) + 1
    return out
