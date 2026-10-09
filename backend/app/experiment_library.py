from __future__ import annotations
"""
Experiment Library (spec section 12/13).

Each template is a structured definition — never a raw natural-language
AI-generated command (spec section 13's "never execute raw AI-generated
natural-language commands" rule). app.experiment_generator instantiates
these against the failure points actually discovered in a given project;
app.safety_gate validates every instance before it's allowed to run.

risk_level: 1 (low) .. 3 (complex) — drives the timeout bucket
  (spec section 19 "Experiment limits").
"""

TEMPLATES = {
    # ---- HTTP / API category ----
    "malformed_request": {
        "category": "http",
        "name": "Malformed request body",
        "risk_level": 1,
        "expected_behavior": "Service returns a 4xx error with a clear message, "
                              "and keeps serving subsequent requests.",
        "safety_requirements": ["target must be a discovered HTTP endpoint",
                                 "no destructive payloads sent"],
    },
    "empty_input": {
        "category": "http",
        "name": "Empty request body",
        "risk_level": 1,
        "expected_behavior": "Service returns a 4xx error rather than crashing "
                              "or hanging on an empty body.",
        "safety_requirements": ["target must be a discovered HTTP endpoint"],
    },
    "oversized_payload": {
        "category": "http",
        "name": "Oversized request payload",
        "risk_level": 1,
        "expected_behavior": "Service rejects the oversized body (413/400) "
                              "instead of exhausting memory or hanging.",
        "safety_requirements": ["payload size bounded by MVP_SAFE single-file limit"],
    },
    "boundary_input": {
        "category": "http",
        "name": "Boundary / unexpected-type input",
        "risk_level": 1,
        "expected_behavior": "Service validates input types/ranges and returns "
                              "a 4xx error rather than an unhandled exception.",
        "safety_requirements": ["target must be a discovered HTTP endpoint"],
    },
    "invalid_content_type": {
        "category": "http",
        "name": "Mismatched Content-Type header",
        "risk_level": 1,
        "expected_behavior": "Service either enforces the declared content type "
                              "with a 4xx, or explicitly documents that it's "
                              "permissive — not an unhandled exception either way.",
        "safety_requirements": ["target must be a discovered HTTP endpoint"],
    },
    "request_burst": {
        "category": "http",
        "name": "Concurrent request burst",
        "risk_level": 2,
        "expected_behavior": "Service serves concurrent requests without "
                              "crashing; 429/backpressure is fine, 5xx or "
                              "connection failures are not (spec section 12).",
        "safety_requirements": ["bounded to MVP_SAFE concurrent-request limits"],
    },
    "wrong_http_method": {
        "category": "http",
        "name": "Wrong request method",
        "risk_level": 1,
        "expected_behavior": "Service answers 405 (or another 4xx) for a method it does not "
                              "support instead of crashing or returning a 5xx.",
        "safety_requirements": ["target must be a discovered HTTP endpoint"],
    },
    "null_json_body": {
        "category": "http",
        "name": "Empty JSON value (null) as body",
        "risk_level": 1,
        "expected_behavior": "Service rejects a body that is valid JSON but not an object "
                              "with a 4xx instead of an unhandled exception.",
        "safety_requirements": ["target must be a discovered HTTP endpoint"],
    },
    "special_characters": {
        "category": "http",
        "name": "Special characters and emoji in input",
        "risk_level": 1,
        "expected_behavior": "Service accepts or cleanly rejects quotes, unicode, emoji and "
                              "HTML/SQL-looking text without a 5xx or crash.",
        "safety_requirements": ["payload is inert text sent only to the sandboxed copy"],
    },
    "long_url": {
        "category": "http",
        "name": "Very long URL",
        "risk_level": 1,
        "expected_behavior": "Service handles a very long URL with a 4xx (for example 414) or a "
                              "normal answer, without crashing.",
        "safety_requirements": ["URL length bounded to a few KB"],
    },
    "unknown_route": {
        "category": "http",
        "name": "Page that does not exist",
        "risk_level": 1,
        "expected_behavior": "Service returns 404 for an unknown path instead of a 5xx error.",
        "safety_requirements": ["target must be a discovered HTTP endpoint"],
    },
    "deeply_nested_json": {
        "category": "http",
        "name": "Deeply nested JSON body",
        "risk_level": 1,
        "expected_behavior": "Service rejects extremely nested JSON with a 4xx instead of "
                              "crashing on recursion limits.",
        "safety_requirements": ["nesting depth bounded to a few thousand levels"],
    },
    "connection_refused": {
        "category": "network",
        "name": "Downstream connection refused",
        "risk_level": 1,
        "expected_behavior": "Any code path that depends on this being reachable "
                              "fails with a handled error, not a hang or crash.",
        "safety_requirements": ["target port must be closed/unused, never a live "
                                 "third-party host"],
    },
    "slow_response": {
        "category": "network",
        "name": "Bounded added latency / client-side timeout probe",
        "risk_level": 2,
        "expected_behavior": "Caller-side timeout triggers cleanly within the "
                              "MVP_SAFE bound instead of hanging indefinitely.",
        "safety_requirements": ["latency bounded by MVP maximum latency (10s)"],
    },

    # ---- Process category ----
    "process_kill": {
        "category": "process",
        "name": "Ungraceful process termination (SIGKILL)",
        "risk_level": 2,
        "expected_behavior": "Process exits; if the architecture has a "
                              "supervisor/restart mechanism it should recover "
                              "(recovery is tested separately by "
                              "process_kill_recovery).",
        "safety_requirements": ["only the sandboxed copy's process is ever "
                                 "signaled, never a host process"],
    },
    "process_kill_recovery": {
        "category": "process",
        "name": "Recovery after ungraceful termination",
        "risk_level": 2,
        "expected_behavior": "A simple restart-on-crash supervisor brings the "
                              "service back to a working state within a "
                              "bounded window (spec section 24, restart strategy).",
        "safety_requirements": ["only the sandboxed copy's process is ever "
                                 "signaled or restarted, never a host process",
                                 "bounded number of restart attempts"],
    },

    # ---- Environment category ----
    "missing_env_var": {
        "category": "configuration",
        "name": "Missing required environment variable",
        "risk_level": 1,
        "expected_behavior": "Service fails fast with a clear startup error, or "
                              "falls back to a documented default — not a silent "
                              "misconfiguration.",
        "safety_requirements": ["only affects the sandboxed copy's process env"],
    },

    # ---- Filesystem category ----
    "missing_file": {
        "category": "filesystem",
        "name": "Missing required file",
        "risk_level": 1,
        "expected_behavior": "Service handles the missing file with a clear "
                              "error instead of an unhandled exception/stack trace.",
        "safety_requirements": ["only ever removes a file from the isolated "
                                 "sandbox copy, never the original upload"],
    },
    "permission_denied": {
        "category": "filesystem",
        "name": "File permission denied",
        "risk_level": 1,
        "expected_behavior": "Service handles a permission error with a clear "
                              "message instead of an unhandled exception.",
        "safety_requirements": ["only ever chmods a file inside the isolated "
                                 "sandbox copy"],
    },

    # ---- Database category (only generated if a DB signal was detected) ----
    "db_connection_refused": {
        "category": "database",
        "name": "Database unavailable",
        "risk_level": 2,
        "expected_behavior": "Service surfaces a clear connection error / "
                              "retries, instead of hanging or crashing.",
        "safety_requirements": ["target must be the sandboxed copy's own "
                                 "configured DB endpoint, never a shared/prod DB"],
    },
}
