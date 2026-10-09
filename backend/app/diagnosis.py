from __future__ import annotations
"""
AI Diagnosis (spec section 23).

Two diagnosers behind one interface:

  - RuleBasedDiagnoser: the MVP default. Fully offline, deterministic,
    and genuinely evidence-grounded — every field is derived from the
    actual observed data (exception class, status code, exit code), not
    a canned string. This is what actually runs in this sandbox.

  - LLMDiagnoser: calls out to app/llm_providers.py, which sends the
    same structured evidence bundle the rule-based diagnoser uses to
    whichever LLM provider/key is next in the rotation (Anthropic,
    OpenAI, Gemini, DeepSeek, Groq, or OpenRouter — see that module's
    docstring for configuration), for a richer root-cause narrative than
    pattern-matching can produce. The code is real and complete, but
    this sandbox has no network access — confirmed earlier in this
    session — so it cannot be exercised here. Configure any of the
    provider API key env vars AND set ENABLE_LLM_DIAGNOSIS=true in an
    environment with network access to use it — keys alone are
    deliberately not enough (see app/llm_providers.py:diagnosis_enabled)
    so pasting keys in doesn't silently start spending them.
    diagnose_run() falls back to the rule-based diagnoser automatically
    if every configured provider/key fails, including "no network" and
    "no keys configured."

Both return the exact structured schema from spec section 23. The AI
(either one) never executes anything — it only ever produces this JSON,
which the caller stores; it cannot control sandboxes, limits, or
permissions (spec section 42).
"""
import json
import re
import sys

from app import llm_providers

MAX_DIAGNOSIS_INPUT_BYTES = 100 * 1024


def diagnose_run(experiment: dict, detection_result: dict, profile: dict) -> dict:
    """Entry point used by the API layer. Tries the LLM diagnoser only if
    llm_providers.diagnosis_enabled() is true — which requires BOTH at
    least one configured provider key AND the separate ENABLE_LLM_DIAGNOSIS
    opt-in (having keys present is not enough by itself; see
    app/llm_providers.py). Falls back to the rule-based diagnoser
    (which always succeeds) on any failure across every configured
    provider/key, or whenever the LLM path isn't enabled at all.

    The fallback is silent to the END USER on purpose: whatever went
    wrong with a provider (rate limit, bad key, outage, malformed
    response) is server plumbing, not something a person looking at a
    tutor explanation should ever see. It's logged to stderr for the
    operator instead — never folded into the returned diagnosis, which
    always reads as a clean, self-contained explanation either way."""
    if detection_result.get("outcome") == "TARGET_UNREACHABLE":
        # The service never started, so no fault was injected and there is
        # nothing for a model to reason about beyond what stderr already says.
        # The deterministic startup diagnosis is more accurate than an LLM
        # guessing at it, and doesn't spend a provider call.
        return _rule_based_diagnose(experiment, detection_result, profile)
    if llm_providers.diagnosis_enabled():
        try:
            return _llm_diagnose(experiment, detection_result, profile)
        except Exception as e:
            print(f"[diagnosis] LLM diagnosis failed for experiment "
                  f"'{experiment.get('name')}', falling back to rule-based: {e}", file=sys.stderr)
            return _rule_based_diagnose(experiment, detection_result, profile)
    return _rule_based_diagnose(experiment, detection_result, profile)


def _rule_based_diagnose(experiment: dict, detection_result: dict, profile: dict) -> dict:
    outcome = detection_result["outcome"]
    reasoning = detection_result["reasoning"]
    result = detection_result["evidence"]
    stderr_all = (result.get("stderr") or "")[-20000:]
    # The exception is the LAST line of a traceback: taking the first 2000
    # characters (as before) dropped it for any traceback longer than that,
    # which is every Flask/Django one.
    stderr = stderr_all[-4000:]
    exc_type, exc_line = _extract_exception(stderr)

    evidence = [reasoning]
    if exc_type:
        evidence.append(f"observed unhandled exception: {exc_type} ({exc_line})")
    if (result.get("chaos") or {}).get("status") is not None:
        evidence.append(f"observed HTTP status: {result['chaos']['status']}")
    if result.get("exit_code") is not None:
        evidence.append(f"process exit code: {result['exit_code']}")

    confidence = 0.9 if exc_type else (0.75 if outcome in ("APPLICATION_FAILURE", "CRASHED") else 0.6)

    if outcome == "TARGET_UNREACHABLE":
        startup = _diagnose_startup_failure(stderr_all, result.get("exit_code"), reasoning)
        return {
            "failure": startup["failure"],
            "root_cause": startup["root_cause"],
            "affected_component": experiment["target"],
            "impact": "this experiment could not run: the service never started, so the fault "
                      "was never injected and nothing was tested",
            "evidence": evidence,
            "recommended_fix": startup["fix"],
            "resilience_pattern": "fail-fast configuration validation",
            "confidence": startup["confidence"],
            "method": "rule_based",
            "setup_issue": True,
        }

    if outcome in ("APPLICATION_FAILURE", "CRASHED"):
        outcome_phrase = {
            "APPLICATION_FAILURE": "an application failure",
            "CRASHED": "a crash",
        }[outcome]
        failure = f"{experiment['name']} caused {outcome_phrase}"
        root_cause = (
            f"an unhandled {exc_type} in the code path exercised by this experiment"
            if exc_type else
            "the code path exercised by this experiment does not handle this fault "
            "class (no error handling / validation observed around it)"
        )
        recommended_fix = _recommended_fix(experiment["fault_type"], exc_type)
        pattern = _resilience_pattern(experiment["fault_type"])
    elif outcome == "WEAK_HANDLING":
        failure = f"{experiment['name']} was accepted without validation"
        root_cause = "input validation is missing or too permissive on this code path"
        recommended_fix = "add explicit input validation (type/range/required-field checks) " \
                           "and return a 4xx response for invalid input"
        pattern = "input validation"
    elif outcome == "RECOVERED":
        failure = None
        root_cause = None
        recommended_fix = None
        pattern = "restart / process supervision"
    else:
        failure = None
        root_cause = None
        recommended_fix = None
        pattern = _resilience_pattern(experiment["fault_type"])  # e.g. "PASSED" on connection_refused -> still informative

    return {
        "failure": failure,
        "root_cause": root_cause,
        "affected_component": experiment["target"],
        "impact": _impact(outcome, experiment),
        "evidence": evidence,
        "recommended_fix": recommended_fix,
        "resilience_pattern": pattern,
        "confidence": confidence,
        "method": "rule_based",
    }


_PORT_IN_USE = re.compile(r"EADDRINUSE|address already in use|WinError 10048|"
                          r"only one usage of each socket address", re.I)


def _diagnose_startup_failure(stderr: str, exit_code, reasoning: str) -> dict:
    """Explain why a service never became reachable, from what it printed.

    This is the most common real-world failure by far (the project's
    dependencies aren't installed on this machine), and it used to be reported
    as "handled correctly / no change needed" because nothing matched."""
    m = re.search(r"(?:ModuleNotFoundError|ImportError): No module named ['\"]([\w.\-]+)['\"]", stderr)
    if m:
        mod = m.group(1)
        top = mod.split(".")[0]
        return {
            "failure": f"Service failed to start: Python package '{top}' is not installed",
            "root_cause": (f"the project imports '{mod}', but no package named '{top}' is installed in the "
                           "Python environment that runs Chaos Tutor, so the service exited during startup "
                           "before any fault could be injected"),
            "fix": (f"install the project's dependencies into that same Python environment "
                    f"(e.g. `pip install -r requirements.txt`, or `pip install {top}` - the PyPI name can "
                    "differ from the import name), then run the test again"),
            "confidence": 0.95,
        }
    m = re.search(r"Cannot find module '([^']+)'", stderr)
    if m:
        name = m.group(1)
        if name.startswith((".", "/")) or re.match(r"^[A-Za-z]:[\\/]", name):
            return {
                "failure": f"Service failed to start: required file '{name}' is missing",
                "root_cause": "the entry point requires a local file that does not exist in the project "
                              "(check the path and its upper/lower-case spelling)",
                "fix": "add the missing file or correct the require()/import path, then run the test again",
                "confidence": 0.9,
            }
        return {
            "failure": f"Service failed to start: Node module '{name}' is not installed",
            "root_cause": (f"the project requires '{name}', but the project has no node_modules folder "
                           "containing it, so the service exited during startup before any fault could be injected"),
            "fix": "run `npm install` in the project folder so node_modules exists, then re-analyze and run the test again",
            "confidence": 0.95,
        }
    if _PORT_IN_USE.search(stderr):
        return {
            "failure": "Service failed to start: its port is already in use",
            "root_cause": ("the service tried to listen on a port that is already taken - it most likely has a "
                           "hard-coded port instead of reading the PORT environment variable Chaos Tutor sets "
                           "for every run"),
            "fix": "read the port from the PORT environment variable (for example "
                   "`int(os.environ.get('PORT', 8000))` or `process.env.PORT || 3000`)",
            "confidence": 0.9,
        }
    if "SyntaxError" in stderr:
        line = next((l.strip() for l in reversed(stderr.splitlines()) if "SyntaxError" in l), "SyntaxError")
        return {
            "failure": "Service failed to start: the code has a syntax error",
            "root_cause": f"the entry point could not be parsed ({line[:160]})",
            "fix": "fix the syntax error shown in the evidence, then run the test again",
            "confidence": 0.95,
        }
    exc_type, exc_line = _extract_exception(stderr)
    if exc_type:
        return {
            "failure": f"Service failed to start: {exc_type}",
            "root_cause": (f"the service raised {exc_type} ({exc_line}) while starting, before it began "
                           "listening - so the injected fault never had a chance to run"),
            "fix": "fix the startup error shown in the evidence (missing configuration, dependency or file), "
                   "then run the test again",
            "confidence": 0.8,
        }
    if "process/thread limit" in (reasoning or ""):
        return {
            "failure": "Service failed to start: the sandbox hit a process/thread limit",
            "root_cause": "the sandbox's resource limits stopped the service from starting - this is not a problem in the project",
            "fix": "run this test again on its own",
            "confidence": 0.7,
        }
    if exit_code not in (None, 0):
        return {
            "failure": "Service failed to start: it exited during startup",
            "root_cause": f"the process exited with code {exit_code} before it began listening, and printed no error",
            "fix": "run the project from the Cloud IDE to see why it exits immediately",
            "confidence": 0.6,
        }
    return {
        "failure": "Service started but never began listening on the assigned port",
        "root_cause": ("the service was still running but nothing accepted connections on the PORT that Chaos "
                       "Tutor assigned - it may ignore the PORT environment variable, or take longer than the "
                       "startup limit to become ready"),
        "fix": "make the service read its port from the PORT environment variable and start listening promptly",
        "confidence": 0.5,
    }


def _extract_exception(stderr: str):
    if not stderr:
        return None, None
    lines = stderr.strip().splitlines()
    for line in reversed(lines):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):\s*(.*)$", line.strip())
        if m:
            return m.group(1), m.group(2)[:200]
    return None, None


def _impact(outcome, experiment):
    if outcome in ("APPLICATION_FAILURE", "CRASHED"):
        return f"a {experiment['category']} fault against {experiment['target']} can take the " \
               f"service down or leave it in an error state with no clean recovery path observed"
    if outcome == "WEAK_HANDLING":
        return "invalid input reaches application logic unchecked, which is a data-integrity " \
               "and potential security risk, not just a robustness gap"
    return "no negative impact observed for this fault"


def _recommended_fix(fault_type, exc_type):
    fixes = {
        "malformed_request": "validate/parse the request body, catch the parsing error, and "
                              "return 400 with a clear message on parse failure",
        "empty_input": "reject empty bodies explicitly with a 400 before attempting to use them",
        "oversized_payload": "enforce a request size limit (e.g. reject via Content-Length check) "
                              "before reading the full body into memory",
        "boundary_input": "validate field types/ranges explicitly rather than trusting client input",
        "wrong_http_method": "return 405 Method Not Allowed for methods the route does not support",
        "null_json_body": "check that the parsed JSON is an object (dict) before using it, and return 400 otherwise",
        "special_characters": "treat all text as data: use parameterised queries and escape output instead of building strings from input",
        "long_url": "limit URL/query length at the server or proxy and return 414 or 400 for oversized URLs",
        "unknown_route": "add a catch-all handler that returns a clean 404 instead of raising an error",
        "deeply_nested_json": "limit request size/nesting and catch RecursionError while parsing, returning 400",
        "missing_env_var": "check for required env vars at startup and fail with a clear message, "
                            "or define a documented default",
        "missing_file": "check that the required file exists (or catch the resulting error) before "
                         "reading it, and fail at startup with an actionable message instead of "
                         "letting the raw error surface",
        "permission_denied": "check file permissions before reading (or catch the resulting error) "
                              "and fail at startup with an actionable message",
    }
    return fixes.get(fault_type, "add explicit error handling around this code path")


def _resilience_pattern(fault_type):
    patterns = {
        "malformed_request": "input validation", "empty_input": "input validation",
        "oversized_payload": "request size limiting", "boundary_input": "input validation",
        "invalid_content_type": "input validation",
        "wrong_http_method": "input validation", "null_json_body": "input validation",
        "special_characters": "input sanitisation", "long_url": "request size limiting",
        "unknown_route": "graceful error handling", "deeply_nested_json": "input validation",
        "missing_env_var": "fail-fast configuration validation",
        "missing_file": "graceful degradation / clear startup error",
        "permission_denied": "graceful degradation / clear startup error",
        "connection_refused": "fail-fast availability signaling",
        "slow_response": "timeout handling",
        "process_kill": "clean failure visibility",
        "process_kill_recovery": "restart / process supervision",
        "request_burst": "backpressure / concurrency handling",
        "db_connection_refused": "fail-fast availability signaling",
    }
    return patterns.get(fault_type, "error handling")


# ------------------------------------------------------------- LLM path
# Real, complete implementation — not exercised in this sandbox (no
# network). Delegates provider/key selection and rotation to
# app/llm_providers.py.

def _llm_diagnose(experiment: dict, detection_result: dict, profile: dict) -> dict:
    evidence_bundle = {
        "experiment": {k: experiment[k] for k in
                       ("name", "category", "target", "fault_type", "expected_behavior")},
        "outcome": detection_result["outcome"],
        "reasoning": detection_result["reasoning"],
        "observed": {
            k: v for k, v in detection_result["evidence"].items()
            if k in ("chaos", "baseline", "stderr", "exit_code", "service_ready")
        },
        "project_framework": profile.get("framework"),
    }
    payload_str = json.dumps(evidence_bundle, default=str)[:MAX_DIAGNOSIS_INPUT_BYTES]

    system_prompt = (
        "You are a chaos-engineering diagnosis assistant. You will be given "
        "structured evidence from ONE experiment run: the fault injected, the "
        "detected outcome, and raw observations (HTTP status, stderr, exit "
        "code). Respond with ONLY a JSON object with exactly these keys: "
        "failure, root_cause, affected_component, impact, evidence (array of "
        "strings), recommended_fix, resilience_pattern, confidence (0.0-1.0). "
        "Only state what the evidence supports; if evidence is insufficient "
        "for a field, say so explicitly rather than inventing detail. Never "
        "include markdown fences or any text outside the JSON object."
    )

    parsed = llm_providers.diagnose_with_llm(system_prompt, payload_str)
    parsed["method"] = "llm"
    parsed.setdefault("evidence", [])
    return parsed
