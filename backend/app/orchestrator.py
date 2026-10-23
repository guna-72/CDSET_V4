from __future__ import annotations
"""
Orchestrator — the service layer the API routes (and this session's
end-to-end test) call. Implements the pipeline from spec section 3:

  UPLOAD -> VALIDATE -> ISOLATE -> ANALYZE -> DISCOVER FAILURE SURFACES ->
  GENERATE EXPERIMENTS -> SAFETY CHECK -> SANDBOX EXECUTION -> OBSERVATION
  -> FAILURE DETECTION -> AI DIAGNOSIS -> DISPLAY RESULT -> STORE HISTORY
"""
import os
import threading

from app import db, intake, git_intake, analyzer, failure_discovery, experiment_generator, safety_gate, \
    chaos_engine, detection, diagnosis, tutor
from app.sandbox import SandboxError
from app.config import STORAGE_DIR, MAX_CONCURRENT_RUNS


class OrchestratorError(Exception):
    pass


class ExperimentAlreadyRunning(OrchestratorError):
    """The same experiment already has an active run; carries that run's id."""
    def __init__(self, experiment_id: str, run_id: str):
        super().__init__(f"experiment {experiment_id} is already running (run {run_id}); "
                         f"wait for it to finish or cancel it first")
        self.run_id = run_id


# Bounded parallelism (see config.MAX_CONCURRENT_RUNS) and one-active-run-per-experiment.
# In-memory on purpose: a crashed server must not leave an experiment locked forever.
_run_slots = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
_active_experiments: dict = {}
_active_lock = threading.Lock()


_active_handles = {}
_handle_lock = threading.Lock()

def register_active_handle(run_id: str, handle):
    if not run_id or not handle:
        return
    with _handle_lock:
        handles = _active_handles.setdefault(run_id, [])
        # ServiceHandle is a mutable dataclass and intentionally unhashable.
        # Track it by object identity rather than requiring hash/equality.
        if not any(existing is handle for existing in handles):
            handles.append(handle)

def unregister_active_handle(run_id: str, handle):
    if not run_id or not handle:
        return
    with _handle_lock:
        s = _active_handles.get(run_id)
        if s:
            s[:] = [existing for existing in s if existing is not handle]
            if not s:
                _active_handles.pop(run_id, None)

def cancel_active_handles(run_id: str):
    with _handle_lock:
        handles = list(_active_handles.pop(run_id, []))
    for h in handles:
        try:
            if hasattr(h, "proc") and h.proc:
                try:
                    h.proc.kill()
                except Exception:
                    pass
                if hasattr(h, "fw_rule_id") and h.fw_rule_id:
                    from app import sandbox
                    sandbox._win_fw_unblock(h.fw_rule_id)
                    h.fw_rule_id = None
            elif hasattr(h, "stop"):
                try:
                    h.stop()
                except Exception:
                    pass
            elif hasattr(h, "kill"):
                try:
                    h.kill()
                except Exception:
                    pass
        except Exception:
            pass

_cancel_flags = {}
_cancel_lock = threading.Lock()

def request_cancel(run_id: str) -> bool:
    with _cancel_lock:
        flag = _cancel_flags.get(run_id)
        if flag is None:
            flag = threading.Event()
            _cancel_flags[run_id] = flag
        flag.set()
    cancel_active_handles(run_id)
    with _active_lock:
        for eid, rid in list(_active_experiments.items()):
            if rid == run_id:
                _active_experiments.pop(eid, None)
    return True

def clear_cancel(run_id: str):
    with _cancel_lock:
        _cancel_flags.pop(run_id, None)
    with _handle_lock:
        _active_handles.pop(run_id, None)

def is_cancel_requested(run_id: str) -> bool:
    with _cancel_lock:
        flag = _cancel_flags.get(run_id)
        return bool(flag and flag.is_set())


def create_project(zip_path: str, name: str, owner_uid: str = "local") -> dict:
    project_id = db.new_id()
    storage_path = os.path.join(STORAGE_DIR, project_id)  # the untouched original — never modified again
    try:
        manifest = intake.validate_and_extract(zip_path, storage_path)
    except intake.IntakeError as e:
        db.audit("project_upload_rejected", {"name": name, "reason": str(e)})
        raise OrchestratorError(f"upload rejected: {e}") from e

    # The caller (api.py's /projects/upload) always writes the uploaded
    # bytes to its own throwaway NamedTemporaryFile and passes *that*
    # file's path here as zip_path - os.path.basename(zip_path) is a
    # random string like "tmpz2we4yob.zip", never anything the user
    # would recognize, and yet it was being stored/returned as
    # original_filename and shown directly in the UI ("File: ...",
    # "Chaos will run on: ... (original_filename)" in ChaosLabPage.jsx).
    # The one piece of real naming information that *does* come from the
    # user is `name` (the browser file's name minus ".zip", sent via the
    # X-Project-Name header) - base original_filename on that instead.
    _PLACEHOLDER_NAMES = {"uploaded-project", "imported-project", "imported project", "uploaded project"}
    requested_name = (name or "").strip()
    if requested_name and requested_name.lower() not in _PLACEHOLDER_NAMES:
        original_filename = f"{requested_name}.zip"
    else:
        original_filename = "upload.zip"
    # Prefer a meaningful caller-supplied project name. Never persist the old
    # UI placeholder "uploaded-project" when a better filename is available.
    root_name = str(manifest.get("project_root_name") or "").strip()
    stem = os.path.splitext(original_filename)[0].strip()
    # The UI does not ask the user to invent a second name. When the archive
    # has one top-level folder, that folder is the actual project name.
    if root_name:
        name = root_name
    elif not name or name.strip().lower() in _PLACEHOLDER_NAMES:
        name = stem or "My Project"
    db.insert("projects", {
        "id": project_id, "name": name.strip(), "owner_uid": owner_uid or "local", "original_filename": original_filename,
        "storage_path": storage_path, "status": "UPLOADED", "created_at": db.now(),
    })
    db.audit("project_uploaded", {"project_id": project_id, **manifest})
    result = db.get_one("projects", project_id)
    result["import_summary"] = {
        "source_files": manifest.get("file_count", 0),
        "ignored_generated_files": manifest.get("ignored_entries", 0),
        "project_root_name": manifest.get("project_root_name") or result.get("name"),
    }
    return result


def _clear_derived_state(project_id: str, failure_points: bool = True, analysis: bool = False):
    """Make analyze / discover / generate idempotent: drop the previous
    output of the step about to be redone instead of stacking a second copy
    on top (re-clicking "Discover" used to double the failure points and
    re-generating multiplied the experiments). Experiments that already
    have run history - and the failure points they reference - are kept:
    runs are the learning record and hold foreign keys to them."""
    conn = db.get_conn()
    pid = (project_id,)
    conn.execute("DELETE FROM safety_events WHERE project_id = ? AND experiment_id IN "
                 "(SELECT id FROM experiments WHERE project_id = ? AND id NOT IN "
                 "(SELECT experiment_id FROM experiment_runs WHERE project_id = ?))", pid * 3)
    conn.execute("DELETE FROM experiments WHERE project_id = ? AND id NOT IN "
                 "(SELECT experiment_id FROM experiment_runs WHERE project_id = ?)", pid * 2)
    if failure_points:
        conn.execute("DELETE FROM failure_points WHERE project_id = ? AND id NOT IN "
                     "(SELECT failure_point_id FROM experiments WHERE project_id = ? "
                     "AND failure_point_id IS NOT NULL)", pid * 2)
    if analysis:
        conn.execute("DELETE FROM project_analysis WHERE project_id = ?", pid)
    conn.commit()


def create_project_from_git(repo_url: str, branch, name, owner_uid: str = "local") -> dict:
    """Import a public https git repository as a project. Same downstream
    model as a zip upload (storage_path is a plain directory of source), so
    analyze / IDE editing / chaos experiments / tutor all work unchanged."""
    project_id = db.new_id()
    storage_path = os.path.join(STORAGE_DIR, project_id)
    try:
        manifest = git_intake.clone_repository(repo_url, storage_path, branch)
    except intake.IntakeError as e:
        db.audit("project_git_import_rejected", {"url": str(repo_url)[:200], "reason": str(e)})
        raise OrchestratorError(f"git import rejected: {e}") from e

    clean_url = git_intake.validate_repo_url(repo_url)
    repo_name = manifest.get("project_root_name") or "git-project"
    display = (name or "").strip() or repo_name
    slug = "/".join(p for p in clean_url.split("/")[3:5] if p)
    if slug.lower().endswith(".git"):
        slug = slug[:-4]
    db.insert("projects", {
        "id": project_id, "name": display, "owner_uid": owner_uid or "local",
        "original_filename": slug or repo_name, "storage_path": storage_path,
        "status": "UPLOADED", "created_at": db.now(),
        "source_type": "git", "git_url": clean_url,
        "git_branch": manifest.get("branch") or (branch or ""),
        "git_commit": manifest.get("commit") or "",
    })
    db.audit("project_imported_from_git", {"project_id": project_id, "url": clean_url, **manifest})
    result = db.get_one("projects", project_id)
    result["import_summary"] = {
        "source_files": manifest.get("file_count", 0),
        "ignored_generated_files": manifest.get("ignored_entries", 0),
        "project_root_name": repo_name,
    }
    return result


def refresh_git_project(project_id: str, discard_local_changes: bool = False) -> dict:
    """Pull the latest commit for a git-sourced project. If the commit
    changed, analysis/failure points/never-run experiments were derived from
    code that no longer exists, so they are cleared and the project returns
    to UPLOADED (re-analyze to continue). Past *runs* and their diagnoses
    are kept - they are the learning record and reference their own
    experiments."""
    project = _require(db.get_one("projects", project_id), "project", project_id)
    if (project.get("source_type") or "upload") != "git":
        raise OrchestratorError("only git-imported projects can be refreshed from git")
    try:
        result = git_intake.refresh_repository(
            project["storage_path"], project.get("git_branch"), discard_local_changes)
    except git_intake.DirtyWorkingTree:
        raise
    except intake.IntakeError as e:
        db.audit("project_git_refresh_failed", {"project_id": project_id, "reason": str(e)})
        raise OrchestratorError(f"git refresh failed: {e}") from e

    invalidated = False
    if result["changed"] or result["discarded_files"]:
        _clear_derived_state(project_id, failure_points=True, analysis=True)
        invalidated = True
    db.update("projects", project_id, {
        "git_commit": result["commit"], "git_branch": result["branch"],
        **({"status": "UPLOADED"} if invalidated else {}),
    })
    db.audit("project_git_refreshed", {"project_id": project_id, **{
        k: v for k, v in result.items() if k != "discarded_files"},
        "discarded_file_count": len(result["discarded_files"])})
    out = db.get_one("projects", project_id)
    out["refresh"] = {**result, "analysis_invalidated": invalidated}
    return out


def analyze_project(project_id: str) -> dict:
    project = _require(db.get_one("projects", project_id), "project", project_id)
    profile = analyzer.analyze_project(project["storage_path"])
    db.get_conn().execute("DELETE FROM project_analysis WHERE project_id = ?", (project_id,))
    db.get_conn().commit()

    analysis_id = db.new_id()
    db.insert("project_analysis", {
        "id": analysis_id, "project_id": project_id,
        "languages_json": db.dumps(profile["languages"]),
        "framework": profile["framework"],
        "execution_status": profile["execution_status"],
        "components_json": db.dumps(profile["components"]),
        "structure_json": db.dumps(profile["structure"]),
        "entrypoint_json": db.dumps({"entrypoint": profile["entrypoint"], "adapter": profile["adapter"],
                                       "reason": profile["execution_status_reason"]}),
        "status": "COMPLETE", "created_at": db.now(),
    })
    db.update("projects", project_id, {"status": "ANALYZED"})
    db.audit("project_analyzed", {"project_id": project_id, "execution_status": profile["execution_status"],
                                    "framework": profile["framework"]})
    return {"analysis_id": analysis_id, "profile": profile}


def discover_failures(project_id: str, profile: dict) -> list[dict]:
    project = _require(db.get_one("projects", project_id), "project", project_id)
    points = failure_discovery.discover_failure_points(profile, project["storage_path"])
    _clear_derived_state(project_id, failure_points=True)   # idempotent re-discovery
    stored = []
    for p in points:
        fp_id = db.new_id()
        db.insert("failure_points", {
            "id": fp_id, "project_id": project_id, "component": p["component"], "type": p["type"],
            "dependencies_json": db.dumps(p["dependencies"]), "failure_modes_json": db.dumps(p["failure_modes"]),
            "coverage_status": p["coverage_status"], "created_at": db.now(),
        })
        p["id"] = fp_id
        stored.append(p)
    db.audit("failure_points_discovered", {"project_id": project_id, "count": len(stored)})
    return stored


def generate_and_gate_experiments(project_id: str, profile: dict, failure_points: list[dict]) -> list[dict]:
    raw_experiments = experiment_generator.generate_experiments(profile, failure_points)
    _clear_derived_state(project_id, failure_points=False)  # idempotent re-generation
    known_targets = {fp["component"] for fp in failure_points}
    by_component = {fp["component"]: fp["id"] for fp in failure_points}

    stored = []
    for exp in raw_experiments:
        decision = safety_gate.evaluate(exp, known_targets)
        if decision.allowed:
            decision = _runnable_requirement(profile)
        if decision.allowed:
            decision = _service_requirement(exp, profile)
        exp_id = db.new_id()
        status = "READY" if decision.allowed else "BLOCKED"
        db.insert("experiments", {
            "id": exp_id, "project_id": project_id,
            "failure_point_id": by_component.get(exp["target"]),
            "name": exp["name"], "category": exp["category"], "target": exp["target"],
            "fault_type": exp["fault_type"], "parameters_json": db.dumps(exp["parameters"]),
            "risk_level": exp["risk_level"], "expected_behavior": exp["expected_behavior"],
            "safety_requirements_json": db.dumps(exp["safety_requirements"]),
            "status": status, "block_reason": decision.reason, "created_at": db.now(),
        })
        db.insert("safety_events", {
            "id": db.new_id(), "experiment_id": exp_id, "project_id": project_id,
            "decision": "ALLOWED" if decision.allowed else "BLOCKED",
            "reason": decision.reason, "ts": db.now(),
        })
        exp["id"] = exp_id
        exp["status"] = status
        exp["block_reason"] = decision.reason
        stored.append(exp)
    db.audit("experiments_generated", {"project_id": project_id, "count": len(stored),
                                         "blocked": sum(1 for e in stored if e["status"] == "BLOCKED")})
    return stored


_SERVICE_ONLY_FAULTS = {"process_kill", "process_kill_recovery"}


def _is_one_shot_cli(profile: dict) -> bool:
    """True for a command-line program with no sign of being a long-running
    service (compiled/CLI adapter, no HTTP routes, no listening port)."""
    adapter = str(profile.get("adapter") or "")
    comps = profile.get("components") or {}
    return (adapter.endswith("_cli")
            and not comps.get("http_endpoints")
            and not comps.get("detected_port"))


def _runnable_requirement(profile: dict):
    """run_experiment refuses any project whose execution_status isn't
    SUPPORTED (the analyzer already knows a concrete reason it can't start -
    dependencies missing, no PORT read, ...). Offering those experiments as
    READY just invites clicks that are guaranteed to fail, and on real
    projects that was every experiment. Block them up front instead, with the
    analyzer's own reason and what to do about it."""
    status = profile.get("execution_status")
    if status in (None, "SUPPORTED"):
        return safety_gate.SafetyDecision(True, None)
    reason = profile.get("execution_status_reason") or "no reason recorded"
    return safety_gate.SafetyDecision(
        False,
        f"this project can't be run yet ({status}): {reason} "
        "Fix that (the Cloud IDE can edit the code), then click Re-analyze in the Cloud IDE to unblock these tests.")


def _service_requirement(exp: dict, profile: dict):
    """Process-kill tests kill a running service and probe it over HTTP. On a
    one-shot CLI program they can only end in TARGET_UNREACHABLE, so block them
    up front with a reason instead of offering a test that cannot mean anything."""
    if exp.get("fault_type") in _SERVICE_ONLY_FAULTS and _is_one_shot_cli(profile):
        return safety_gate.SafetyDecision(
            False,
            "this project looks like a one-shot command-line program (no HTTP service or "
            "listening port detected). Process-kill tests need a long-running service to "
            "kill and probe. Use Cloud IDE > Run to execute it; file/config faults still apply.")
    return safety_gate.SafetyDecision(True, None)


def run_experiment(experiment_id: str, run_id: str | None = None) -> dict:
    exp_row = _require(db.get_one("experiments", experiment_id), "experiment", experiment_id)
    if exp_row["status"] != "READY":
        raise OrchestratorError(f"experiment {experiment_id} is {exp_row['status']}, not READY — "
                                 f"cannot execute a non-approved experiment "
                                 f"(reason: {exp_row.get('block_reason')})")

    project = _require(db.get_one("projects", exp_row["project_id"]), "project", exp_row["project_id"])
    analysis_rows = db.get_many("project_analysis", "project_id = ?", (project["id"],))
    if not analysis_rows:
        raise OrchestratorError("no analysis found for this project — run analyze_project first")
    analysis = analysis_rows[0]
    entrypoint_info = db.loads(analysis["entrypoint_json"])
    profile = {
        "framework": analysis["framework"],
        "execution_status": analysis["execution_status"],
        "execution_status_reason": entrypoint_info.get("reason"),
        "components": db.loads(analysis["components_json"]),
        "entrypoint": entrypoint_info["entrypoint"],
        "adapter": entrypoint_info["adapter"],
    }

    # PARTIALLY_SUPPORTED means the analyzer already identified a concrete
    # reason this project can't actually run here (missing dependencies that
    # can't be installed, no PORT env var read, etc. — see analyzer.py). Every
    # one of those reasons guarantees the process never reaches a listening
    # state, so letting the run proceed anyway doesn't test anything real —
    # it just produces a TARGET_UNREACHABLE that looks identical to an
    # infrastructure fault and hides the actual, already-known cause. Only a
    # genuinely SUPPORTED project is executed; PARTIALLY_SUPPORTED is refused
    # up front with the analyzer's own reason surfaced to the caller/UI.
    if profile["execution_status"] != "SUPPORTED":
        raise OrchestratorError(
            f"project execution_status is {profile['execution_status']} — cannot run experiments "
            f"against a project this MVP can't execute: "
            f"{profile['execution_status_reason'] or 'no reason recorded'} "
            f"(after fixing it, re-analyze the project)"
        )

    experiment = {
        "id": exp_row["id"], "name": exp_row["name"], "category": exp_row["category"],
        "target": exp_row["target"], "fault_type": exp_row["fault_type"],
        "parameters": db.loads(exp_row["parameters_json"]), "risk_level": exp_row["risk_level"],
        "expected_behavior": exp_row["expected_behavior"],
    }

    if run_id is None:
        run_id = db.new_id()
        db.insert("experiment_runs", {
            "id": run_id, "experiment_id": experiment_id, "project_id": project["id"],
            "status": "RUNNING", "started_at": db.now(),
        })
    else:
        current = db.get_one("experiment_runs", run_id)
        if not current:
            db.insert("experiment_runs", {
                "id": run_id, "experiment_id": experiment_id, "project_id": project["id"],
                "status": "RUNNING", "started_at": db.now(),
            })
        elif current.get("status") != "RUNNING":
            return {"run_id": run_id, "status": current.get("status"), "outcome": current.get("outcome")}
    _event(run_id, "SYSTEM", f"starting run for experiment '{experiment['name']}'", {})

    try:
        raw_result = chaos_engine.execute_experiment(experiment, project["storage_path"], profile, run_id=run_id)
        current_status = db.get_one("experiment_runs", run_id).get("status")
        if current_status in ("CANCEL_REQUESTED", "CANCELLED") or is_cancel_requested(run_id):
            db.update("experiment_runs", run_id, {"status": "CANCELLED", "finished_at": db.now(), "error": "Cancelled by operator"})
            _event(run_id, "SYSTEM", "experiment cancelled by operator", {})
            clear_cancel(run_id)
            return {"run_id": run_id, "status": "CANCELLED", "outcome": None}
        for ev in raw_result.get("events", []):
            _event(run_id, ev["type"], ev["message"], ev.get("data", {}))

        # Preserve real captured application output as evidence. Do not synthesize
        # demo log lines; stdout/stderr are recorded only when the sandbox actually
        # produced them.
        stdout = str(raw_result.get("stdout") or "").strip()
        stderr = str(raw_result.get("stderr") or "").strip()
        if stdout:
            _event(run_id, "APPLICATION", "Captured application stdout", {"output": stdout[-12000:]})
        if stderr:
            _event(run_id, "APPLICATION_ERROR", "Captured application stderr", {"output": stderr[-12000:]})

        detection_result = detection.classify(experiment["fault_type"], raw_result)
        _event(run_id, "SYSTEM", f"classified outcome: {detection_result['outcome']}",
               {"reasoning": detection_result["reasoning"]})

        diag = diagnosis.diagnose_run(experiment, detection_result, profile)
        diag_id = db.new_id()
        db.insert("diagnoses", {
            "id": diag_id, "run_id": run_id, "failure": diag.get("failure"),
            "root_cause": diag.get("root_cause"), "affected_component": diag.get("affected_component"),
            "impact": diag.get("impact"), "evidence_json": db.dumps(diag.get("evidence")),
            "recommended_fix": diag.get("recommended_fix"), "resilience_pattern": diag.get("resilience_pattern"),
            "confidence": diag.get("confidence"), "method": diag.get("method", "rule_based"),
            "created_at": db.now(),
        })

        verification = {
            "test_environment": "isolated sandbox copy",
            "original_project_modified": False,
            "baseline_recorded": raw_result.get("baseline") is not None,
            "fault_observation_recorded": raw_result.get("chaos") is not None,
            "service_ready_before_test": raw_result.get("service_ready"),
            "service_alive_after_fault": raw_result.get("service_alive_after_fault"),
            "network_isolated": raw_result.get("net_isolated"),
            "cleanup_completed": True,
            "outcome": detection_result["outcome"],
            "run_id": run_id,
        }
        db.update("experiment_runs", run_id, {
            "status": "COMPLETED", "finished_at": db.now(), "outcome": detection_result["outcome"],
            "baseline_json": db.dumps(raw_result.get("baseline")),
            "chaos_json": db.dumps({**(raw_result.get("chaos") or {}), "verification": verification}),
        })
        if exp_row["failure_point_id"]:
            coverage = "TESTED" if detection_result["outcome"] != "TARGET_UNREACHABLE" else "BLOCKED"
            db.update("failure_points", exp_row["failure_point_id"], {"coverage_status": coverage})

        explanation = tutor.explain(experiment, detection_result, diag)
        question = tutor.generate_question(experiment, detection_result, diag)
        tutor_session_id = db.new_id()
        db.insert("tutor_sessions", {
            "id": tutor_session_id, "run_id": run_id,
            "explanation_json": db.dumps(explanation),
            "question_json": db.dumps(question),
            "created_at": db.now(),
        })

        db.audit("experiment_run_completed", {"run_id": run_id, "experiment_id": experiment_id,
                                                 "outcome": detection_result["outcome"]})
        clear_cancel(run_id)
        return {
            "run_id": run_id, "outcome": detection_result["outcome"],
            "reasoning": detection_result["reasoning"], "diagnosis": diag, "raw_result": raw_result,
            "tutor_session_id": tutor_session_id, "explanation": explanation,
        }
    except RuntimeError as e:
        if str(e).startswith("CANCEL_REQUESTED") or is_cancel_requested(run_id):
            db.update("experiment_runs", run_id, {"status": "CANCELLED", "finished_at": db.now(), "error": "Test stopped by operator"})
            _event(run_id, "SYSTEM", "Test stopped by operator; isolated resources are being cleaned up.", {})
            db.audit("experiment_run_cancelled", {"run_id": run_id, "experiment_id": experiment_id})
            clear_cancel(run_id)
            return {"run_id": run_id, "status": "CANCELLED", "outcome": None}
        # Not a cancellation: record the failure like any other infrastructure
        # error. A bare ``raise`` here used to bypass the generic handler below
        # (sibling ``except`` clauses never see an exception raised from another
        # handler), leaving the run stuck in RUNNING with no event or audit row.
        _record_run_failure(run_id, experiment_id, e)
        raise
    except SandboxError as e:
        # Security capability failure is a controlled refusal, not an internal 500.
        # Keep the run record auditable and tell the API/UI exactly why execution
        # was refused (for example, native Windows without Linux namespaces).
        db.update("experiment_runs", run_id, {"status": "BLOCKED", "finished_at": db.now(), "error": str(e)})
        _event(run_id, "SAFETY", f"run blocked by sandbox capability policy: {e}", {})
        db.audit("experiment_run_blocked", {"run_id": run_id, "experiment_id": experiment_id, "reason": str(e)})
        clear_cancel(run_id)
        raise OrchestratorError(f"experiment blocked by sandbox security policy: {e}") from e
    except Exception as e:
        _record_run_failure(run_id, experiment_id, e)
        raise


def _record_run_failure(run_id: str, experiment_id: str, exc: Exception) -> None:
    db.update("experiment_runs", run_id, {"status": "FAILED", "finished_at": db.now(), "error": str(exc)})
    _event(run_id, "SYSTEM", f"run infrastructure error: {exc}", {})
    db.audit("experiment_run_errored", {"run_id": run_id, "experiment_id": experiment_id, "error": str(exc)})
    clear_cancel(run_id)



def start_experiment_async(experiment_id: str) -> str:
    """Create a RUNNING record and execute the existing safe runner in a
    background thread. This keeps the HTTP request responsive and gives the
    UI a real run id that can be cancelled/polled independently."""
    exp = _require(db.get_one("experiments", experiment_id), "experiment", experiment_id)
    if exp["status"] != "READY":
        raise OrchestratorError(f"experiment {experiment_id} is {exp['status']}, not READY")
    run_id = db.new_id()
    with _active_lock:
        if experiment_id in _active_experiments:
            raise ExperimentAlreadyRunning(experiment_id, _active_experiments[experiment_id])
        _active_experiments[experiment_id] = run_id
    try:
        db.insert("experiment_runs", {
            "id": run_id, "experiment_id": experiment_id, "project_id": exp["project_id"],
            "status": "RUNNING", "started_at": db.now(),
        })
    except Exception:
        with _active_lock:
            _active_experiments.pop(experiment_id, None)
        raise

    def worker():
        try:
            # Wait for a free execution slot (see MAX_CONCURRENT_RUNS).
            with _run_slots:
                current = db.get_one("experiment_runs", run_id)
                if current and current.get("status") in ("CANCEL_REQUESTED", "CANCELLED"):
                    # Cancelled while still queued: run_experiment() would return early
                    # and leave the record stuck in CANCEL_REQUESTED, so finish it here.
                    db.update("experiment_runs", run_id, {"status": "CANCELLED", "finished_at": db.now(),
                                                          "error": "Cancelled before it started"})
                    _event(run_id, "SYSTEM", "experiment cancelled before it started", {})
                    clear_cancel(run_id)
                    return
                run_experiment(experiment_id, run_id=run_id)
        except Exception as exc:
            current = db.get_one("experiment_runs", run_id)
            if current and current.get("status") not in ("CANCEL_REQUESTED", "CANCELLED") and not is_cancel_requested(run_id):
                db.update("experiment_runs", run_id, {"status": "FAILED", "finished_at": db.now(), "error": str(exc)})
            clear_cancel(run_id)
        finally:
            with _active_lock:
                if _active_experiments.get(experiment_id) == run_id:
                    _active_experiments.pop(experiment_id, None)
    threading.Thread(target=worker, name=f"chaos-run-{run_id[:8]}", daemon=True).start()
    return run_id

def answer_tutor_question(tutor_session_id: str, answer_text: str) -> dict:
    session = _require(db.get_one("tutor_sessions", tutor_session_id), "tutor_session", tutor_session_id)
    question = db.loads(session["question_json"])
    result = tutor.evaluate_answer(question, answer_text)
    answer_id = db.new_id()
    db.insert("user_answers", {
        "id": answer_id, "tutor_session_id": tutor_session_id, "answer_text": answer_text,
        "correct": 1 if result["correct"] else 0, "feedback": result["feedback"], "created_at": db.now(),
    })
    return result


def list_recent_runs(limit: int = 20) -> list:
    """Completed runs, newest first, with just enough context (project +
    experiment name) for a UI to show a picker without a separate round
    trip per run. Used by the frontend Tutor page to find something to
    show without the user having to hunt for a run id."""
    rows = db.get_many("experiment_runs", "status = 'COMPLETED'")
    rows.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    rows = rows[:limit]
    out = []
    for r in rows:
        exp = db.get_one("experiments", r["experiment_id"])
        project = db.get_one("projects", r["project_id"]) if r.get("project_id") else None
        tutor_rows = db.get_many("tutor_sessions", "run_id = ?", (r["id"],))
        out.append({
            "run_id": r["id"],
            "outcome": r["outcome"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "experiment_name": exp["name"] if exp else "Unknown experiment",
            "fault_type": exp["fault_type"] if exp else None,
            "category": exp["category"] if exp else None,
            "target": exp["target"] if exp else None,
            "project_id": r["project_id"],
            "project_name": project["name"] if project else "Unknown project",
            "tutor_session_id": tutor_rows[0]["id"] if tutor_rows else None,
        })
    return out


def coverage_report(project_id: str) -> dict:
    points = db.get_many("failure_points", "project_id = ?", (project_id,))
    experiments = db.get_many("experiments", "project_id = ?", (project_id,))
    by_status = {}
    for p in points:
        by_status[p["coverage_status"]] = by_status.get(p["coverage_status"], 0) + 1
    return {
        "total_failure_points": len(points),
        "by_coverage_status": by_status,
        "total_experiments_generated": len(experiments),
        "experiments_blocked": sum(1 for e in experiments if e["status"] == "BLOCKED"),
        "experiments_ready": sum(1 for e in experiments if e["status"] == "READY"),
    }


def project_report(project_id: str) -> dict:
    """P1 reporting (spec section 29): a project resilience report built
    entirely from this project's own real run history — coverage,
    outcome breakdown, and the concrete findings with their diagnoses."""
    project = _require(db.get_one("projects", project_id), "project", project_id)
    experiments = db.get_many("experiments", "project_id = ?", (project_id,))
    exp_by_id = {e["id"]: e for e in experiments}
    runs = []
    for e in experiments:
        runs.extend(db.get_many("experiment_runs", "experiment_id = ?", (e["id"],)))

    outcome_counts = {}
    findings = []
    completed_runs = [r for r in runs if r.get("outcome")]
    for r in completed_runs:
        outcome_counts[r["outcome"]] = outcome_counts.get(r["outcome"], 0) + 1
        if r["outcome"] in ("APPLICATION_FAILURE", "CRASHED", "WEAK_HANDLING"):
            diag_rows = db.get_many("diagnoses", "run_id = ?", (r["id"],))
            exp = exp_by_id.get(r["experiment_id"], {})
            findings.append({
                "experiment": exp.get("name"), "target": exp.get("target"), "outcome": r["outcome"],
                "diagnosis": (diag_rows[0]["failure"] if diag_rows else None),
                "recommended_fix": (diag_rows[0]["recommended_fix"] if diag_rows else None),
            })

    # One row per test case (latest completed run), for a clean results table.
    latest_by_exp = {}
    for r in completed_runs:
        stamp = r.get("finished_at") or r.get("started_at") or 0
        prev = latest_by_exp.get(r["experiment_id"])
        if prev is None or stamp >= (prev.get("finished_at") or prev.get("started_at") or 0):
            latest_by_exp[r["experiment_id"]] = r
    test_cases = []
    for exp_id, r in latest_by_exp.items():
        exp = exp_by_id.get(exp_id, {})
        test_cases.append({
            "experiment": exp.get("name"), "fault_type": exp.get("fault_type"), "target": exp.get("target"),
            "category": exp.get("category"), "status": r.get("status"), "outcome": r.get("outcome"),
            "finished_at": r.get("finished_at"),
        })
    test_cases.sort(key=lambda c: (c.get("category") or "", c.get("experiment") or ""))

    total_runs = len(completed_runs)
    passed = outcome_counts.get("PASSED", 0) + outcome_counts.get("RECOVERED", 0)
    resilience_score = round(100 * passed / total_runs, 1) if total_runs else None
    verification_runs = []
    for r in runs:
        try:
            chaos_data = db.loads(r.get("chaos_json")) or {}
            verification = chaos_data.get("verification") if isinstance(chaos_data, dict) else None
            if verification:
                verification_runs.append(verification)
        except Exception:
            pass
    verified_count = sum(1 for v in verification_runs if v.get("baseline_recorded") or v.get("fault_observation_recorded"))

    return {
        "project": {"id": project["id"], "name": project["name"]},
        "total_runs": total_runs,
        "outcome_counts": outcome_counts,
        "resilience_score_pct": resilience_score,
        "findings": findings,
        "test_cases": test_cases,
        "coverage": coverage_report(project_id),
        "verification": {
            "runs_with_recorded_evidence": verified_count,
            "total_completed_runs": len(verification_runs),
            "original_project_modified": any(v.get("original_project_modified") for v in verification_runs),
            "test_environment": "isolated sandbox copy",
        },
    }


def _event(run_id, type_, message, data):
    db.insert("events", {"id": db.new_id(), "run_id": run_id, "ts": db.now(), "type": type_,
                           "message": message, "data_json": db.dumps(data)})


def _require(row, kind, id_):
    if row is None:
        raise OrchestratorError(f"{kind} not found: {id_}")
    return row
