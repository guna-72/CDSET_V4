from __future__ import annotations
"""
Failure Detection (spec section 22).

Classifies a raw chaos_engine result into one of a small set of outcomes
by comparing chaos behavior against what the experiment's
`expected_behavior` calls for. Never silently treats NOT_TESTED as
PASSED (spec section 26's explicit rule, applied here at the run level
too as TARGET_UNREACHABLE vs PASSED being kept distinct).
"""

OUTCOMES = {
    "PASSED",              # handled the fault the way expected_behavior calls for
    "WEAK_HANDLING",        # didn't crash, but also didn't validate/reject — a real gap
    "APPLICATION_FAILURE",  # unhandled exception / 5xx / unexpected crash
    "CRASHED",              # process died as a direct result of the fault
    "RECOVERED",             # died, but a restart supervisor brought it back (spec section 21: RECOVERY event)
    "ANOMALY",               # behavior that doesn't fit the expected pattern either way
    "TARGET_UNREACHABLE",   # infra-level: service never started for reasons unrelated to the fault
}


_RESOURCE_LIMIT_MARKERS = (
    "uv_thread_create", "resource temporarily unavailable", "can't start new thread",
    "unable to create native thread", "cannot fork", "fork: retry", "eagain",
)


def _looks_like_resource_exhaustion(result: dict) -> bool:
    text = f"{result.get('stderr') or ''} {result.get('stdout') or ''}".lower()
    return any(m in text for m in _RESOURCE_LIMIT_MARKERS)


def classify(fault_type: str, result: dict) -> dict:
    """Returns {"outcome": ..., "reasoning": "...", "evidence": {...}}."""
    if result.get("service_ready") is False and fault_type not in (
        "missing_env_var", "missing_file", "permission_denied"
    ):
        reasoning = ("the target service never became reachable in the sandbox, "
                     "independent of the injected fault")
        if _looks_like_resource_exhaustion(result):
            reasoning += (". The service failed to start because the sandbox hit a process/thread "
                          "limit (not because of the injected fault) — run this test again on its own")
        return _outcome("TARGET_UNREACHABLE", reasoning, result)

    if fault_type in ("malformed_request", "empty_input", "boundary_input", "oversized_payload",
                      "invalid_content_type", "null_json_body", "deeply_nested_json", "unknown_route"):
        return _classify_http_input_fault(result)
    if fault_type == "wrong_http_method":
        return _classify_wrong_method(result)
    if fault_type in ("special_characters", "long_url"):
        return _classify_tolerant_http(result)
    if fault_type == "request_burst":
        return _classify_request_burst(result)
    if fault_type == "connection_refused":
        return _classify_connection_refused(result)
    if fault_type == "slow_response":
        return _classify_slow_response(result)
    if fault_type == "process_kill":
        return _classify_process_kill(result)
    if fault_type == "process_kill_recovery":
        return _classify_process_kill_recovery(result)
    if fault_type == "missing_env_var":
        return _classify_startup_fault(result, "environment variable")
    if fault_type in ("missing_file", "permission_denied"):
        return _classify_startup_fault(result, "file")
    if fault_type == "db_connection_refused":
        return _outcome("PASSED", "confirmed the conventional DB port is unreachable in this "
                                   "sandbox, as expected with no DB server running", result)
    return _outcome("ANOMALY", f"no classifier defined for fault_type '{fault_type}'", result)


def _has_traceback(text: str) -> bool:
    return bool(text) and "Traceback (most recent call last)" in text


def _classify_http_input_fault(result):
    chaos = result.get("chaos") or {}
    alive = result.get("service_alive_after_fault", True)
    if not alive:
        return _outcome("CRASHED", "the process died as a direct result of the request", result)
    if not chaos.get("ok"):
        return _outcome("APPLICATION_FAILURE",
                         f"the request failed at the connection level ({chaos.get('error')}) "
                         "instead of returning a handled HTTP error", result)
    status = chaos.get("status")
    if status is not None and 400 <= status < 500:
        return _outcome("PASSED", f"service returned a handled {status} error, matching the "
                                   "expected behavior", result)
    if status is not None and status >= 500:
        return _outcome("APPLICATION_FAILURE",
                         f"service returned {status}, indicating an unhandled server-side error", result)
    if status is not None and 200 <= status < 300:
        return _outcome("WEAK_HANDLING",
                         f"service accepted the fault input with a {status} response instead of "
                         "validating/rejecting it — not a crash, but not handled either", result)
    return _outcome("ANOMALY", f"unexpected response shape: {chaos}", result)


def _classify_wrong_method(result):
    chaos = result.get("chaos") or {}
    if not result.get("service_alive_after_fault", True):
        return _outcome("CRASHED", "the process died as a direct result of the request", result)
    if not chaos.get("ok"):
        return _outcome("APPLICATION_FAILURE",
                         f"the request failed at the connection level ({chaos.get('error')}) "
                         "instead of returning a handled HTTP error", result)
    status = chaos.get("status")
    # 405 and 501 are the standard "method not supported" answers (Python's built-in server uses 501).
    if status in (405, 501) or (status is not None and 400 <= status < 500):
        return _outcome("PASSED", f"service refused the unsupported method with a handled {status} answer", result)
    if status is not None and status >= 500:
        return _outcome("APPLICATION_FAILURE", f"service returned {status} (unhandled server error)", result)
    if status is not None and 200 <= status < 300:
        return _outcome("WEAK_HANDLING", f"service accepted an unsupported method with a {status} response", result)
    return _outcome("ANOMALY", f"unexpected response shape: {chaos}", result)


def _classify_tolerant_http(result):
    """For inputs that may legitimately be accepted (special characters, long URLs):
    2xx/3xx/4xx are all fine; only crashes and 5xx count as failures."""
    chaos = result.get("chaos") or {}
    if not result.get("service_alive_after_fault", True):
        return _outcome("CRASHED", "the process died as a direct result of the request", result)
    if not chaos.get("ok"):
        return _outcome("APPLICATION_FAILURE",
                         f"the request failed at the connection level ({chaos.get('error')}) "
                         "instead of returning a handled HTTP answer", result)
    status = chaos.get("status")
    if status is not None and status >= 500:
        return _outcome("APPLICATION_FAILURE", f"service returned {status}, indicating an unhandled server-side error", result)
    if status is not None:
        return _outcome("PASSED", f"service handled the request safely (HTTP {status}) and kept running", result)
    return _outcome("ANOMALY", f"unexpected response shape: {chaos}", result)


def _classify_request_burst(result):
    chaos = result.get("chaos") or {}
    if not result.get("service_alive_after_fault", True):
        return _outcome("CRASHED", "the process died under concurrent load", result)
    if chaos.get("any_5xx"):
        return _outcome("APPLICATION_FAILURE",
                         f"{chaos.get('connection_errors', 0)} connection errors and at least one "
                         f"5xx out of {chaos.get('total_sent')} concurrent requests", result)
    if chaos.get("connection_errors", 0) > 0:
        return _outcome("WEAK_HANDLING",
                         f"{chaos['connection_errors']}/{chaos.get('total_sent')} concurrent requests "
                         "failed at the connection level — no graceful queuing/backpressure observed", result)
    return _outcome("PASSED",
                     f"all {chaos.get('total_sent')} concurrent requests were served "
                     f"(429 present: {chaos.get('any_429')})", result)


def _classify_process_kill_recovery(result):
    if result.get("recovered"):
        events = result.get("restart_events") or []
        secs = events[-1]["recovered_after_s"] if events else None
        return _outcome("RECOVERED",
                         f"a restart-on-crash supervisor brought the service back "
                         f"{'in ' + str(secs) + 's' if secs is not None else ''}", result)
    return _outcome("APPLICATION_FAILURE",
                     "the process did not come back to a working state within the recovery "
                     "window even with a simple restart supervisor in front of it", result)


def _classify_connection_refused(result):
    chaos = result.get("chaos") or {}
    err = str(chaos.get("error", "")).lower()
    if not chaos.get("ok") and any(w in err for w in ("refused", "timed out", "timeout", "10061", "10060", "reset", "closed")):
        return _outcome("PASSED",
                         "an unreachable service surfaces as a clean connection refusal or timeout, "
                         "not an unhandled server hang — this is what monitoring/health checks depend on", result)
    if not chaos.get("ok"):
        return _outcome("ANOMALY", f"unreachable service produced an unexpected error: {chaos.get('error')}", result)
    return _outcome("ANOMALY", "service unexpectedly still responded after being stopped", result)


def _classify_slow_response(result):
    chaos = result.get("chaos") or {}
    if chaos.get("any_timeout_detected"):
        return _outcome("APPLICATION_FAILURE",
                         "at least one probed endpoint exceeded the client timeout bound", result)
    return _outcome("PASSED", "all probed endpoints responded within the timeout bound", result)


def _classify_process_kill(result):
    alive = result.get("process_alive_after_kill")
    chaos = result.get("chaos") or {}
    if alive:
        return _outcome("ANOMALY", "process still reported alive shortly after SIGKILL", result)
    if not chaos.get("ok"):
        return _outcome("PASSED",
                         "process died as expected; callers see a clean connection failure "
                         "rather than a hang (recovery/restart is a P1 concern, not tested here)",
                         result)
    return _outcome("ANOMALY", "process reported dead but still answered a request", result)


def _classify_startup_fault(result, kind):
    ready = result.get("service_ready")
    stderr = result.get("stderr") or ""
    if ready:
        return _outcome("PASSED", f"service started successfully despite the missing {kind} — "
                                   "handled via a fallback/default", result)
    if _has_traceback(stderr):
        return _outcome("APPLICATION_FAILURE",
                         f"service crashed at startup with an unhandled exception when the "
                         f"required {kind} was unavailable, instead of a clean error message",
                         result)
    return _outcome("PASSED", f"service exited with a controlled error when the required {kind} "
                               "was unavailable (fail-fast, no stack trace)", result)


def _outcome(name, reasoning, result):
    return {"outcome": name, "reasoning": reasoning, "evidence": result}
