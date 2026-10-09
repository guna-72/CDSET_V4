from __future__ import annotations
"""
Failure-Surface Discovery (spec section 15).

Turns a ProjectProfile (from app.analyzer) into a list of FailurePoints —
concrete, project-specific places a fault could be injected. This is the
piece that keeps the system "project-aware": no HTTP surface detected ->
no HTTP failure points -> no HTTP experiments generated later. No database
signal -> no database failure points. Etc.
"""

from app.config import SYSTEM_ENV_KEYS

DATA_DIR_HINTS = {"data", "config", "conf", "fixtures", "seed", "seeds"}


def discover_failure_points(profile: dict, project_dir: str) -> list[dict]:
    points = []

    if profile["execution_status"] in ("SUPPORTED", "PARTIALLY_SUPPORTED"):
        # HTTP surface — present if we found endpoints, a port, or the
        # framework itself is inherently HTTP (Flask/FastAPI/Express/generic http)
        is_http_capable = bool(
            profile["components"]["http_endpoints"]
            or profile["components"]["detected_port"]
            or profile.get("adapter") in (
                "python_flask", "python_fastapi", "node_express", "python_generic_http",
                "node_generic",
            )
        )
        if is_http_capable:
            points.append({
                "component": "http_api",
                "type": "network_interface",
                "dependencies": [],
                "failure_modes": [
                    "malformed_request", "oversized_payload", "empty_input",
                    "boundary_input", "connection_refused", "slow_response",
                    "wrong_http_method", "null_json_body", "special_characters",
                    "long_url", "unknown_route", "deeply_nested_json",
                ],
            })

        # Process itself is always a valid target for a supported app
        points.append({
            "component": profile.get("entrypoint") or "main_process",
            "type": "process",
            "dependencies": [],
            "failure_modes": ["process_kill"],
        })

        for var in profile["components"]["env_vars"]:
            if var.upper() in SYSTEM_ENV_KEYS:
                continue
            points.append({
                "component": f"env:{var}",
                "type": "environment_variable",
                "dependencies": [],
                "failure_modes": ["missing_env_var"],
            })

        for path in _resolve_filesystem_targets(profile, project_dir):
            points.append({
                "component": f"file:{path}",
                "type": "filesystem",
                "dependencies": [],
                "failure_modes": ["missing_file", "permission_denied"],
            })

        for db in profile["components"]["database_signals"]:
            points.append({
                "component": f"database:{db}",
                "type": "database",
                "dependencies": [],
                "failure_modes": ["connection_refused"],
            })
    else:
        # Detected but not executable here — spec section 9: never
        # silently claim coverage for something we can't actually run.
        points.append({
            "component": profile.get("framework") or "unknown",
            "type": "not_executable",
            "dependencies": [],
            "failure_modes": [],
        })

    for p in points:
        p["coverage_status"] = "NOT_TESTED"
    return points


def _resolve_filesystem_targets(profile, project_dir):
    """Prefer real, code-confirmed file reads (from AST analysis — files
    the code actually calls open() on) over the directory-name heuristic.
    Falls back to the heuristic only when analysis resolved nothing (e.g.
    Node.js, or a path built in a way the analyzer couldn't trace), so a
    project with no statically-resolvable open() calls still gets some
    coverage rather than none."""
    import os as _os
    analyzed_paths = [
        p for p in profile["components"].get("filesystem_paths", [])
        if not _os.path.isabs(p)  # only project-relative paths are safe to target in a sandbox copy
    ]
    resolved = []
    for p in analyzed_paths:
        full = _os.path.normpath(_os.path.join(project_dir, p))
        if _os.path.commonpath([full, project_dir]) == project_dir and _os.path.isfile(full):
            resolved.append(_os.path.normpath(p))
    if resolved:
        return resolved[:5]
    return _find_data_files(project_dir)


def _find_data_files(project_dir):
    import os
    found = []
    ignored = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build", "target", ".next", "coverage"}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in ignored]
        rel_root = os.path.relpath(root, project_dir)
        top = rel_root.split(os.sep)[0].lower() if rel_root != "." else ""
        if top in DATA_DIR_HINTS:
            for f in files:
                found.append(os.path.normpath(os.path.join(rel_root, f)))
    return found[:5]  # bounded — MVP_SAFE, not exhaustive
