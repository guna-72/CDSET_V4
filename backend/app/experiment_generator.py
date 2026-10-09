from __future__ import annotations
"""
Automatic Experiment Generation (spec section 16).

Input: ProjectProfile + FailureSurfaceGraph (failure_points) + the
ExperimentLibrary templates. Output: a bounded, deduplicated,
project-aware ApplicableExperimentSet — matched to the spec's explicit
example: "No database detected -> do not generate database experiments."
"""
import re

from app.experiment_library import TEMPLATES

MAX_EXPERIMENTS = 24


def _concrete_path(path: str) -> str:
    """Turn a declared route pattern into a URL that actually reaches the handler.
    Sending "/tasks/<int:id>" or "/users/:id" literally hits no route (404), and a
    handled-4xx there would be scored as a PASS for a request the app never saw."""
    p = re.sub(r"<[^>]+>", "1", path)
    p = re.sub(r"\{[^}]+\}", "1", p)
    p = re.sub(r"/:[A-Za-z_]\w*\??", "/1", p)
    if not p.startswith("/"):
        p = "/" + p
    return p


def _unique(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def generate_experiments(profile: dict, failure_points: list[dict]) -> list[dict]:
    experiments = []
    endpoints = profile["components"]["http_endpoints"]
    all_paths = _unique(_concrete_path(e["path"]) for e in endpoints
                        if e["path"] and not e["path"].startswith("("))
    post_paths = _unique(_concrete_path(e["path"]) for e in endpoints
                         if e["path"] and not e["path"].startswith("(") and e["method"] == "POST")
    # Body-fault experiments (malformed/empty/oversized/boundary) are only
    # meaningful against a path that actually accepts a body — prefer a
    # discovered POST path; fall back to any known path if none was
    # statically detected (still safe: safety_gate only requires the
    # *component* target to be a real discovered failure point, not the
    # specific path guessed inside it).
    body_fault_paths = (post_paths or all_paths or ["/"])[:3]
    any_paths = (all_paths or ["/"])[:3]

    for fp in failure_points:
        if fp["type"] == "network_interface":
            for fault in ("malformed_request", "empty_input", "oversized_payload", "boundary_input",
                          "invalid_content_type", "null_json_body", "deeply_nested_json",
                          "special_characters", "wrong_http_method"):
                experiments.append(_instantiate(fault, fp, {"candidate_paths": body_fault_paths}))
            for fault in ("connection_refused", "slow_response", "request_burst", "long_url", "unknown_route"):
                experiments.append(_instantiate(fault, fp, {"candidate_paths": any_paths}))
        elif fp["type"] == "process":
            experiments.append(_instantiate("process_kill", fp, {}))
            experiments.append(_instantiate("process_kill_recovery", fp, {}))
        elif fp["type"] == "environment_variable":
            var_name = fp["component"].split(":", 1)[1]
            # PORT is the harness's own readiness-probe control variable in
            # this sandbox, not a meaningful app-config difference to fault
            # inject against — skip it to avoid a meaningless/self-defeating
            # experiment (see app/chaos_engine.py docstring for why).
            if var_name == "PORT":
                continue
            experiments.append(_instantiate("missing_env_var", fp, {"env_var": var_name}))
        elif fp["type"] == "filesystem":
            rel_path = fp["component"].split(":", 1)[1]
            experiments.append(_instantiate("missing_file", fp, {"relative_path": rel_path}))
            experiments.append(_instantiate("permission_denied", fp, {"relative_path": rel_path}))
        elif fp["type"] == "database":
            experiments.append(_instantiate("db_connection_refused", fp, {}))
        # type == "not_executable" -> deliberately generates nothing

    # Deduplicate by fault + target first. A project can have many environment
    # variables or files, but showing ten copies of the same test is not useful
    # to a human operator.
    seen = set()
    deduped = []
    for e in experiments:
        key = (e["fault_type"], e["target"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    # Prefer a diverse, understandable test set. Keep at most one generated
    # test of each fault type in the default list. The detailed failure-point
    # records remain available in the project analysis, so this does not hide
    # what was discovered; it simply prevents the Experiments page from being
    # flooded with near-identical rows such as repeated "Missing Configuration".
    diverse = []
    seen_fault_types = set()
    for e in sorted(deduped, key=lambda x: (x["risk_level"], x["category"], x["name"])):
        if e["fault_type"] in seen_fault_types:
            continue
        seen_fault_types.add(e["fault_type"])
        diverse.append(e)

    # Prioritize: low-risk first, then by category diversity, bounded to
    # MAX_EXPERIMENTS so a large project doesn't produce an unbounded set
    # (spec section 27's "experiment budget" principle applied at
    # generation time too, not just during adaptive exploration).
    diverse.sort(key=lambda e: (e["risk_level"], e["category"], e["name"]))
    return diverse[:MAX_EXPERIMENTS]


def _instantiate(fault_type: str, failure_point: dict, params: dict) -> dict:
    tmpl = TEMPLATES[fault_type]
    return {
        "name": tmpl["name"],
        "category": tmpl["category"],
        "target": failure_point["component"],
        "failure_point_component": failure_point["component"],
        "fault_type": fault_type,
        "parameters": params,
        "risk_level": tmpl["risk_level"],
        "expected_behavior": tmpl["expected_behavior"],
        "safety_requirements": tmpl["safety_requirements"],
    }
