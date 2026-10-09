from __future__ import annotations
"""
Safety Gate (spec section 17).

Every experiment must pass every check here before it may run. Any
failure -> BLOCKED, NOT_EXECUTED, with a specific reason (never a vague
"blocked for safety"). This is the one place in the codebase that decides
"is this experiment allowed to touch a sandbox at all" — chaos_engine.py
refuses to run anything that hasn't come through here with ALLOWED.
"""
from app.experiment_library import TEMPLATES
from app.config import EXPERIMENT_TIMEOUT_MAX

REQUIRED_FIELDS = {"name", "category", "target", "fault_type", "parameters", "risk_level",
                   "expected_behavior", "safety_requirements"}

MAX_RISK_LEVEL = 3
# Resource-exhaustion experiments are disabled by default (spec section 20).
# This is enforced structurally: no such fault_type exists in TEMPLATES, so
# it can never pass schema validation even if something tried to smuggle
# one in via AI-generated parameters.
FORBIDDEN_FAULT_TYPES = {"resource_exhaustion", "host_network_scan", "raw_shell_command"}


class SafetyDecision:
    def __init__(self, allowed: bool, reason: str | None = None):
        self.allowed = allowed
        self.reason = reason


def evaluate(experiment: dict, known_failure_point_components: set[str]) -> SafetyDecision:
    # 1. Schema validation
    missing = REQUIRED_FIELDS - set(experiment.keys())
    if missing:
        return SafetyDecision(False, f"schema validation failed: missing fields {sorted(missing)}")
    if not isinstance(experiment["parameters"], dict):
        return SafetyDecision(False, "schema validation failed: parameters must be an object")

    # 2. Fault-type allowlist (never a raw AI-generated command — spec section 13/42)
    fault_type = experiment["fault_type"]
    if fault_type in FORBIDDEN_FAULT_TYPES:
        return SafetyDecision(False, f"fault_type '{fault_type}' is forbidden by policy")
    if fault_type not in TEMPLATES:
        return SafetyDecision(False, f"fault_type '{fault_type}' is not a recognized library template")

    # 3. Target validation — must be a real, previously-discovered failure
    # point for THIS project, never an arbitrary string.
    target = experiment["target"]
    if target not in known_failure_point_components:
        return SafetyDecision(False,
            f"target '{target}' does not correspond to a discovered failure point "
            "for this project — refusing to inject a fault against an unvalidated target")

    # 4. Scope / risk validation
    risk = experiment["risk_level"]
    if not isinstance(risk, int) or not (1 <= risk <= MAX_RISK_LEVEL):
        return SafetyDecision(False, f"risk_level {risk} is out of the allowed 1-{MAX_RISK_LEVEL} range")

    # 5. Resource validation
    timeout_bucket = {1: 60, 2: 120, 3: 300}[risk]
    if timeout_bucket > EXPERIMENT_TIMEOUT_MAX:
        return SafetyDecision(False, "computed timeout exceeds MVP_SAFE maximum")

    # 6. Network validation — connection-refused / db faults must never
    # carry a caller-supplied external host; the engine always points
    # these at a fixed, closed localhost port (checked here defensively).
    if fault_type in ("connection_refused", "db_connection_refused"):
        host = experiment["parameters"].get("host")
        if host and host not in ("127.0.0.1", "localhost"):
            return SafetyDecision(False,
                f"connection-refused fault must target localhost only, got '{host}'")

    # 7. Rollback validation — every fault in this MVP operates on an
    # ephemeral sandbox copy that's destroyed after the run; nothing here
    # is allowed to reference the original storage path.
    for v in experiment["parameters"].values():
        # Normalise Windows separators so "\\data\\storage\\" cannot slip past.
        if isinstance(v, str) and "/data/storage/" in v.replace("\\", "/"):
            return SafetyDecision(False,
                "experiment parameters reference the original upload storage path "
                "directly — refusing (originals must never be touched)")

    return SafetyDecision(True, None)
