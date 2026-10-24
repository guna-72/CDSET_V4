from __future__ import annotations
"""
API routes — spec section 35, scoped to the P0 subset (recovery/tutor/
coverage-dashboard/exploration endpoints are P1, not implemented here).
Every route is a thin wrapper around app.orchestrator: Frontend -> Route
-> Schema validation -> Service -> Database -> Response, per spec Rule 3.
No disconnected endpoints — every route below does real, traceable work.
"""
import os
import tempfile
import sys
import pathlib
import re

from app import db, orchestrator, tutor, tutor_context
from app import auth
from app.http_framework import Router, HTTPError

router = Router()

@router.get("/health")
def health(req):
    return 200, {"status": "ok", "service": "chaos-tutor-mvp"}



@router.post("/projects/upload")
def upload_project(req):
    from urllib.parse import unquote
    name = unquote(req.headers.get("X-Project-Name", "")).strip()
    # The frontend supplies the filename/folder name, but never allow the
    # generic fallback to become the visible project name when it is absent.
    # The orchestrator also receives the original filename for auditability.
    if not name:
        name = "Imported Project"
    if not req.body:
        raise HTTPError(400, "empty request body — expected a zip archive")
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(req.body)
        tmp_path = f.name
    try:
        project = orchestrator.create_project(tmp_path, name, getattr(req, "user_uid", "local"))
        auth.sync_project(project)
        auth.upload_archive(project, tmp_path)
    except orchestrator.OrchestratorError as e:
        raise HTTPError(400, str(e))
    finally:
        os.remove(tmp_path)
    return 201, project



@router.get("/git/status")
def git_status(req):
    from app import git_intake
    return 200, {"git_available": git_intake.git_available()}


@router.post("/projects/import-git")
def import_git_project(req):
    body = req.json() or {}
    url = body.get("url")
    if not isinstance(url, str) or not url.strip():
        raise HTTPError(400, "url is required (a public https:// git repository)")
    name = body.get("name")
    if name is not None and not isinstance(name, str):
        raise HTTPError(400, "name must be text")
    try:
        project = orchestrator.create_project_from_git(
            url, body.get("branch"), name, getattr(req, "user_uid", "local"))
        auth.sync_project(project)
    except orchestrator.OrchestratorError as e:
        raise HTTPError(400, str(e))
    return 201, project


@router.post("/projects/{id}/git/refresh")
def refresh_git_project(req):
    from app import git_intake
    project = _owned_project(req, req.params["id"])
    body = req.json() if req.body else {}
    body = body or {}
    try:
        updated = orchestrator.refresh_git_project(
            project["id"], discard_local_changes=bool(body.get("discard_local_changes")))
    except git_intake.DirtyWorkingTree as e:
        return 409, {"error": "local_changes",
                     "message": "You have edited files in the IDE that a refresh would overwrite.",
                     "modified_files": e.files[:100]}
    except orchestrator.OrchestratorError as e:
        raise HTTPError(400, str(e))
    return 200, updated


@router.post("/keys/check")
def check_api_key(req):
    """Check an API key without persisting it. Supports built-in providers
    and a custom OpenAI-compatible GET endpoint. Raw secrets never appear
    in the response or audit log."""
    from app import llm_providers
    body = req.json()
    provider = str(body.get("provider", "auto") or "auto")
    key = str(body.get("key", "") or "")
    endpoint = str(body.get("endpoint", "") or "").strip() or None
    if len(key) > 512:
        raise HTTPError(400, "API key is too long")
    if endpoint and (not endpoint.startswith("https://")):
        raise HTTPError(400, "custom verification endpoint must use HTTPS")
    return 200, llm_providers.check_api_key(provider, key, endpoint=endpoint)

@router.get("/keys/status")
def key_status(req):
    """Check every key configured on the backend environment. Secrets are
    never returned; each result is masked and classified."""
    from app import llm_providers
    results = []
    for provider, keys in llm_providers.load_keys().items():
        for index, key in enumerate(keys, 1):
            result = llm_providers.check_api_key(provider, key)
            result["index"] = index
            results.append(result)
    return 200, {
        "keys": results,
        "configured": bool(results),
        "source_info": llm_providers.get_keys_source_info(),
    }


@router.get("/settings/keys")
def get_settings_keys(req):
    """Get status of API keys configured in settings vs backend .env."""
    from app import llm_providers
    saved = llm_providers.get_settings_keys()
    masked_settings = {p: llm_providers._mask(k) for p, k in saved.items() if k}
    return 200, {
        "settings_keys": masked_settings,
        "source_info": llm_providers.get_keys_source_info(),
        "configured": llm_providers.any_keys_configured(),
    }


@router.post("/settings/keys")
def save_settings_keys(req):
    """Save or update API keys in user settings. Empty strings clear the setting
    for that provider so it falls back to the .env file."""
    from app import llm_providers
    body = req.json()
    keys = body.get("keys", body) if isinstance(body, dict) else {}
    if not isinstance(keys, dict):
        raise HTTPError(400, "keys must be an object")
    saved = llm_providers.save_settings_keys(keys)
    masked_settings = {p: llm_providers._mask(k) for p, k in saved.items() if k}
    return 200, {
        "success": True,
        "settings_keys": masked_settings,
        "source_info": llm_providers.get_keys_source_info(),
        "configured": llm_providers.any_keys_configured(),
    }

@router.get("/capabilities")
def capabilities(req):
    from app import sandbox, llm_providers
    import platform, sys
    return 200, {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "network_namespace": sandbox.network_isolation_available(),
        "llm_diagnosis_enabled": llm_providers.diagnosis_enabled(),
        "configured_llm_providers": llm_providers.configured_providers(),
        "authentication_required": bool(os.environ.get("CHAOS_TUTOR_API_TOKEN")) or os.environ.get("FIREBASE_AUTH_REQUIRED", "false").lower() in {"1", "true", "yes", "on"},
        "firebase_auth_configured": auth.firebase_admin_available() if (os.environ.get("FIREBASE_AUTH_REQUIRED") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")) else False,
        "firestore_sync_enabled": auth.firestore_enabled(),
        "storage_sync_enabled": os.environ.get("FIREBASE_SYNC_STORAGE", "false").lower() in {"1", "true", "yes", "on"},
        "degraded_sandbox_allowed": __import__("app.config", fromlist=["ALLOW_DEGRADED_SANDBOX"]).ALLOW_DEGRADED_SANDBOX,
    }

def _owned_project(req, project_id):
    project = db.get_one("projects", project_id)
    if not project:
        raise HTTPError(404, "project not found")
    owner = project.get("owner_uid") or "local"
    if getattr(req, "user_uid", "local") != owner and getattr(req, "actor", "") != "api-token":
        raise HTTPError(403, "you do not have access to this project")
    return project


def _owned_experiment(req, experiment_id):
    exp = db.get_one("experiments", experiment_id)
    if not exp:
        raise HTTPError(404, "experiment not found")
    _owned_project(req, exp["project_id"])
    return exp


def _owned_run(req, run_id):
    run = db.get_one("experiment_runs", run_id)
    if not run:
        raise HTTPError(404, "run not found")
    _owned_project(req, run["project_id"])
    return run


def _owned_tutor(req, session_id):
    session = db.get_one("tutor_sessions", session_id)
    if not session:
        raise HTTPError(404, "tutor session not found")
    _owned_run(req, session["run_id"])
    return session


_MAX_TUTOR_HISTORY_TURNS = 8
_MAX_TUTOR_HISTORY_TEXT_CHARS = 2000


def _sanitize_tutor_history(raw):
    """Client-supplied prior turns for /tutor/{id}/ask, so a follow-up
    question ("what about the second one?") can be answered with the
    actual conversation as context instead of treated in isolation.
    Untrusted input: only a list of {role, text} dicts is accepted, role
    is restricted to user/assistant, text is coerced to a length-capped
    string, and the whole thing is capped to the most recent N turns so
    a client can't blow out the LLM prompt budget."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        if role not in ("user", "assistant"):
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        cleaned.append({"role": role, "text": text.strip()[:_MAX_TUTOR_HISTORY_TEXT_CHARS]})
    return cleaned[-_MAX_TUTOR_HISTORY_TURNS:]


@router.get("/projects")
def list_projects(req):
    uid = getattr(req, "user_uid", "local")
    if getattr(req, "actor", "") == "api-token":
        rows = db.get_many("projects")
    else:
        rows = db.get_many("projects", "owner_uid = ?", (uid,))
    return 200, {"projects": rows}


@router.delete("/projects/{id}")
def delete_project(req):
    project = _owned_project(req, req.params["id"])
    project_id = project["id"]
    # Remove dependent records first because SQLite foreign keys are enabled.
    for table, column in [
        ("user_answers", "tutor_session_id"),
        ("tutor_sessions", "run_id"),
        ("events", "run_id"),
        ("diagnoses", "run_id"),
        ("experiment_runs", "project_id"),
        ("safety_events", "project_id"),
        ("experiments", "project_id"),
        ("failure_points", "project_id"),
        ("project_analysis", "project_id"),
    ]:
        if table == "user_answers":
            db.get_conn().execute("DELETE FROM user_answers WHERE tutor_session_id IN (SELECT id FROM tutor_sessions WHERE run_id IN (SELECT id FROM experiment_runs WHERE project_id = ?))", (project_id,))
        elif table == "tutor_sessions":
            db.get_conn().execute("DELETE FROM tutor_sessions WHERE run_id IN (SELECT id FROM experiment_runs WHERE project_id = ?)", (project_id,))
        elif table in ("events", "diagnoses"):
            db.get_conn().execute(f"DELETE FROM {table} WHERE run_id IN (SELECT id FROM experiment_runs WHERE project_id = ?)", (project_id,))
        else:
            db.get_conn().execute(f"DELETE FROM {table} WHERE {column} = ?", (project_id,))
    db.get_conn().execute("DELETE FROM projects WHERE id = ?", (project_id,))
    db.get_conn().commit()
    from app import git_intake
    git_intake.remove_tree(project["storage_path"])   # handles read-only .git files on Windows
    db.audit("project_deleted", {"project_id": project_id}, actor=getattr(req, "actor", "unknown"))
    return 200, {"deleted": True, "project_id": project_id}


@router.get("/projects/{id}")
def get_project(req):
    project = _owned_project(req, req.params["id"])
    return 200, project


@router.post("/projects/{id}/analyze")
def analyze(req):
    _owned_project(req, req.params["id"])
    try:
        result = orchestrator.analyze_project(req.params["id"])
    except orchestrator.OrchestratorError as e:
        raise HTTPError(404, str(e))
    return 200, {"analysis_id": result["analysis_id"], "profile": result["profile"]}



def _safe_project_file(project, relative_path):
    import pathlib
    rel = (relative_path or "").replace("\\", "/").lstrip("/")
    if not rel or rel in (".", "..") or "\x00" in rel:
        raise HTTPError(400, "invalid file path")
    if rel.startswith("../") or "/../" in rel or rel.endswith("/..") or (len(rel) >= 2 and rel[1] == ":"):
        raise HTTPError(400, "invalid file path")
    if any(part.lower() == ".git" for part in rel.split("/")):
        # Listing already hides .git; the direct read/write endpoints must
        # agree. .git/config would otherwise be readable/editable, and a
        # hand-edited .git can break "refresh from git" or run hooks.
        raise HTTPError(400, "git metadata is not accessible through the IDE")
    base = pathlib.Path(project["storage_path"]).resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPError(400, "file path escapes project workspace")
    if target.is_dir():
        raise HTTPError(400, "path is a directory")
    return target, rel

@router.get("/projects/{id}/files")
def list_project_files(req):
    project = _owned_project(req, req.params["id"])
    import pathlib
    base = pathlib.Path(project["storage_path"]).resolve()
    items = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if any(part.startswith(".chaos_") for part in p.parts):
            continue
        # Dependency/build caches are not source files and can make the IDE
        # appear empty or unusably large for real-world projects.
        ignored_dirs = {"node_modules", "__pycache__", ".venv", "venv", ".git", "dist", "build", ".next", "coverage"}
        if any(part in ignored_dirs for part in p.parts):
            continue
        rel = p.relative_to(base).as_posix()
        # Keep the IDE responsive and avoid exposing runtime secrets.
        if rel in {".env", ".git/config"} or "/.git/" in f"/{rel}":
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        items.append({"path": rel, "name": p.name, "size": size, "kind": "file"})
    return 200, {"files": items, "count": len(items)}

@router.get("/projects/{id}/files/content")
def read_project_file(req):
    project = _owned_project(req, req.params["id"])
    path = (req.query.get("path") or [""])[0]
    target, rel = _safe_project_file(project, path)
    if not target.exists():
        raise HTTPError(404, "file not found")
    if target.stat().st_size > 2 * 1024 * 1024:
        raise HTTPError(413, "file too large for Cloud IDE")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPError(415, "binary files are not editable in Cloud IDE")
    return 200, {"path": rel, "content": content}

def _write_text_keep_newlines(target, content: str):
    """Save IDE text without changing the file's line-ending style.

    The read endpoint uses text mode, so the browser always sees "\\n"; a
    plain write_text() then makes Windows turn *every* "\\n" into "\\r\\n" -
    merely opening and saving an untouched LF file rewrote every line (which
    git reports as a whole-file change), and on other platforms a CRLF file
    silently lost its CRLFs. Write bytes explicitly instead: keep CRLF if the
    existing file mostly used it, otherwise LF (also for new files, so the
    result never depends on which OS the backend runs on).
    """
    try:
        old = target.read_bytes() if target.exists() else b""
    except OSError:
        old = b""
    crlf = old.count(b"\r\n")
    style = "\r\n" if crlf > (old.count(b"\n") - crlf) else "\n"
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    target.write_bytes(normalized.replace("\n", style).encode("utf-8"))


@router.put("/projects/{id}/files/content")
def write_project_file(req):
    project = _owned_project(req, req.params["id"])
    body = req.json() or {}
    target, rel = _safe_project_file(project, body.get("path"))
    content = body.get("content")
    if not isinstance(content, str):
        raise HTTPError(400, "content must be text")
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise HTTPError(413, "file too large for Cloud IDE")
    if any(part.startswith(".chaos_") for part in pathlib.PurePosixPath(rel).parts):
        raise HTTPError(400, "internal harness files cannot be edited")
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_text_keep_newlines(target, content)
    db.audit("ide_file_saved", {"project_id": project["id"], "path": rel}, actor=getattr(req, "actor", "unknown"))
    return 200, {"saved": True, "path": rel}

@router.post("/runs/{id}/cancel")
def cancel_run(req):
    run = _owned_run(req, req.params["id"])
    if run["status"] not in ("RUNNING", "CANCEL_REQUESTED"):
        return 200, {"cancelled": False, "status": run["status"], "message": "Run is not active."}
    orchestrator.request_cancel(run["id"])
    db.update("experiment_runs", run["id"], {"status": "CANCELLED", "finished_at": db.now(), "error": "Test stopped by operator"})
    orchestrator._event(run["id"], "SYSTEM", "Test stopped by operator; isolated resources cleaned up.", {})
    db.audit("experiment_run_cancelled", {"run_id": run["id"], "experiment_id": run["experiment_id"]})
    return 200, {"cancelled": True, "status": "CANCELLED", "message": "Test cancelled."}


@router.get("/projects/{id}/analysis")
def get_analysis(req):
    _owned_project(req, req.params["id"])
    rows = db.get_many("project_analysis", "project_id = ?", (req.params["id"],))
    if not rows:
        raise HTTPError(404, "no analysis found — POST /projects/{id}/analyze first")
    row = rows[0]
    row["languages"] = db.loads(row.pop("languages_json"))
    row["components"] = db.loads(row.pop("components_json"))
    row["structure"] = db.loads(row.pop("structure_json"))
    row["entrypoint"] = db.loads(row.pop("entrypoint_json"))
    return 200, row


@router.post("/projects/{id}/discover-failures")
def discover_failures(req):
    _owned_project(req, req.params["id"])
    analysis_rows = db.get_many("project_analysis", "project_id = ?", (req.params["id"],))
    if not analysis_rows:
        raise HTTPError(400, "run /analyze before discovering failure points")
    profile = _profile_from_analysis_row(analysis_rows[0])
    points = orchestrator.discover_failures(req.params["id"], profile)
    return 200, {"failure_points": points}


@router.get("/projects/{id}/failure-points")
def get_failure_points(req):
    _owned_project(req, req.params["id"])
    points = db.get_many("failure_points", "project_id = ?", (req.params["id"],))
    for p in points:
        p["dependencies"] = db.loads(p.pop("dependencies_json"))
        p["failure_modes"] = db.loads(p.pop("failure_modes_json"))
    return 200, {"failure_points": points}


@router.post("/projects/{id}/generate-experiments")
def generate_experiments(req):
    _owned_project(req, req.params["id"])
    analysis_rows = db.get_many("project_analysis", "project_id = ?", (req.params["id"],))
    if not analysis_rows:
        raise HTTPError(400, "run /analyze before generating experiments")
    profile = _profile_from_analysis_row(analysis_rows[0])
    points_rows = db.get_many("failure_points", "project_id = ?", (req.params["id"],))
    if not points_rows:
        raise HTTPError(400, "run /discover-failures before generating experiments")
    points = []
    for p in points_rows:
        points.append({**p, "dependencies": db.loads(p["dependencies_json"]),
                        "failure_modes": db.loads(p["failure_modes_json"])})
    experiments = orchestrator.generate_and_gate_experiments(req.params["id"], profile, points)
    return 200, {"experiments": experiments}


@router.get("/projects/{id}/experiments")
def list_experiments(req):
    _owned_project(req, req.params["id"])
    rows = db.get_many("experiments", "project_id = ?", (req.params["id"],))
    # Keep the user-facing list useful even for projects imported with an older
    # version that generated several copies of the same fault. Prefer the first
    # instance of each fault type; run history remains attached to the selected
    # experiment and is still available from the individual experiment endpoint.
    unique = []
    seen_faults = set()
    for r in rows:
        fault = r.get("fault_type") or r.get("name")
        if fault in seen_faults:
            continue
        seen_faults.add(fault)
        r["parameters"] = db.loads(r.pop("parameters_json"))
        r["safety_requirements"] = db.loads(r.pop("safety_requirements_json"))
        unique.append(r)
    return 200, {"experiments": unique}


@router.get("/experiments/{id}")
def get_experiment(req):
    _owned_experiment(req, req.params["id"])
    row = db.get_one("experiments", req.params["id"])
    if not row:
        raise HTTPError(404, "experiment not found")
    row["parameters"] = db.loads(row.pop("parameters_json"))
    row["safety_requirements"] = db.loads(row.pop("safety_requirements_json"))
    return 200, row


@router.get("/experiments/{id}/runs")
def list_experiment_runs(req):
    _owned_experiment(req, req.params["id"])
    rows = db.get_many("experiment_runs", "experiment_id = ?", (req.params["id"],))
    for r in rows:
        r["baseline"] = db.loads(r.pop("baseline_json"))
        r["chaos"] = db.loads(r.pop("chaos_json"))
    return 200, {"runs": rows}


@router.post("/experiments/{id}/run")
def run_experiment(req):
    _owned_experiment(req, req.params["id"])
    try:
        run_id = orchestrator.start_experiment_async(req.params["id"])
    except orchestrator.ExperimentAlreadyRunning as e:
        raise HTTPError(409, str(e))
    except orchestrator.OrchestratorError as e:
        raise HTTPError(400, str(e))
    return 202, {"run_id": run_id, "status": "RUNNING", "message": "Experiment started."}


@router.get("/runs")
def list_runs(req):
    limit_raw = (req.query.get("limit") or ["20"])[0]
    try:
        limit = max(1, min(int(limit_raw), 100))
    except ValueError:
        limit = 20
    uid = getattr(req, "user_uid", "local")
    if getattr(req, "actor", "") == "api-token":
        rows = orchestrator.list_recent_runs(limit)
    else:
        rows = db.get_many("experiment_runs", "project_id IN (SELECT id FROM projects WHERE owner_uid = ?)", (uid,))[:limit]
    for r in rows:
        r["baseline"] = db.loads(r.pop("baseline_json", None))
        r["chaos"] = db.loads(r.pop("chaos_json", None))
    return 200, {"runs": rows}


@router.get("/runs/{id}")
def get_run(req):
    _owned_run(req, req.params["id"])
    row = db.get_one("experiment_runs", req.params["id"])
    if not row:
        raise HTTPError(404, "run not found")
    row["baseline"] = db.loads(row.pop("baseline_json"))
    row["chaos"] = db.loads(row.pop("chaos_json"))
    return 200, row


@router.get("/runs/{id}/logs")
def get_run_logs(req):
    _owned_run(req, req.params["id"])
    events = db.get_many("events", "run_id = ?", (req.params["id"],))
    for e in events:
        e["data"] = db.loads(e.pop("data_json"))
    return 200, {"events": events}

@router.get("/projects/{id}/logs")
def get_project_logs(req):
    """Return the project's event stream across its experiment runs.

    This is intentionally separate from /runs/{id}/logs so the Logs page can
    start working immediately after navigation, even before a run id has been
    selected in the browser. Events are returned oldest-first for streaming
    clients, with an optional run_id filter.
    """
    project = _owned_project(req, req.params["id"])
    run_id = (req.query.get("run_id") or [""])[0].strip()
    limit_raw = (req.query.get("limit") or ["500"])[0]
    try:
        limit = max(1, min(int(limit_raw), 1000))
    except ValueError:
        limit = 500
    conn = db.get_conn()
    if run_id:
        _owned_run(req, run_id)
        # Take the most recent ``limit`` events, then present them oldest-first.
        # (A plain ASC + LIMIT returns the *oldest* rows, so once a run/project
        # exceeded the limit the live tail of the log never reached the UI.)
        cur = conn.execute(
            "SELECT * FROM (SELECT rowid AS _rid, * FROM events WHERE run_id = ? "
            "ORDER BY ts DESC, rowid DESC LIMIT ?) ORDER BY ts ASC, _rid ASC",
            (run_id, limit),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM (SELECT e.rowid AS _rid, e.* FROM events e JOIN experiment_runs r ON r.id = e.run_id "
            "WHERE r.project_id = ? ORDER BY e.ts DESC, e.rowid DESC LIMIT ?) ORDER BY ts ASC, _rid ASC",
            (project["id"], limit),
        )
    events = [dict(row) for row in cur.fetchall()]
    for e in events:
        e.pop("_rid", None)
    for e in events:
        e["data"] = db.loads(e.pop("data_json"))
    return 200, {"events": events, "project_id": project["id"], "run_id": run_id or None}


@router.get("/runs/{id}/diagnosis")
def get_run_diagnosis(req):
    _owned_run(req, req.params["id"])
    rows = db.get_many("diagnoses", "run_id = ?", (req.params["id"],))
    if not rows:
        raise HTTPError(404, "no diagnosis found for this run")
    row = rows[0]
    row["evidence"] = db.loads(row.pop("evidence_json"))
    return 200, row


@router.get("/projects/{id}/coverage")
def get_coverage(req):
    _owned_project(req, req.params["id"])
    return 200, orchestrator.coverage_report(req.params["id"])


@router.get("/projects/{id}/report")
def get_report(req):
    _owned_project(req, req.params["id"])
    try:
        return 200, orchestrator.project_report(req.params["id"])
    except orchestrator.OrchestratorError as e:
        raise HTTPError(404, str(e))


@router.get("/runs/{id}/tutor")
def get_tutor_session(req):
    _owned_run(req, req.params["id"])
    rows = db.get_many("tutor_sessions", "run_id = ?", (req.params["id"],))
    if not rows:
        raise HTTPError(404, "no tutor session found for this run")
    row = rows[0]
    question = db.loads(row["question_json"])
    question.pop("_concept", None)  # server-side answer key — never sent to the client
    return 200, {
        "tutor_session_id": row["id"],
        "explanation": db.loads(row["explanation_json"]),
        "question": question,
    }


@router.post("/tutor/{id}/answer")
def answer_tutor_question(req):
    _owned_tutor(req, req.params["id"])
    answer_text = req.json().get("answer", "")
    if not isinstance(answer_text, str):
        raise HTTPError(400, "answer must be text")
    try:
        result = orchestrator.answer_tutor_question(req.params["id"], answer_text)
    except orchestrator.OrchestratorError as e:
        raise HTTPError(404, str(e))
    return 200, result


@router.post("/tutor/{id}/ask")
def ask_tutor(req):
    _owned_tutor(req, req.params["id"])
    body = req.json()
    question = body.get("question") or ""
    if not isinstance(question, str):
        raise HTTPError(400, "question must be text")
    question = question.strip()
    if not question:
        raise HTTPError(400, "question is required")
    history = _sanitize_tutor_history(body.get("history"))
    rows = db.get_many("tutor_sessions", "id = ?", (req.params["id"],))
    if not rows:
        raise HTTPError(404, "tutor session not found")
    session = rows[0]
    run = db.get_one("experiment_runs", session["run_id"])
    if not run:
        raise HTTPError(404, "run not found")
    diag_rows = db.get_many("diagnoses", "run_id = ?", (session["run_id"],))
    diag = diag_rows[0] if diag_rows else None
    evidence = db.loads(diag["evidence_json"]) if diag else {}
    evidence_text = evidence if isinstance(evidence, str) else db.dumps(evidence)
    try:
        code_ctx = tutor_context.build_context(run, use_llm=False)
    except Exception as e:  # the tutor must still answer without code context
        print(f"[api] tutor code context unavailable: {e}", file=sys.stderr)
        code_ctx = None
    code_summary = tutor_context.summarize_for_prompt(code_ctx)
    try:
        ai_backend_res = tutor.answer_with_ai_tutor_backend(
            question, run, diag, evidence_text, history=history, code_context=code_summary
        )
        if ai_backend_res and ai_backend_res.get("answer"):
            return 200, {"answer": ai_backend_res["answer"], "run_id": session["run_id"]}
    except Exception as e:
        print(f"[api] answer_with_ai_tutor_backend error: {e}", file=sys.stderr)

    result = tutor.answer_question(question, run, diag, evidence_text, history=history,
                                   code_context=code_summary)
    return 200, {"answer": result["answer"], "run_id": session["run_id"]}


@router.get("/runs/{id}/tutor-context")
def get_tutor_context(req):
    """Everything the AI Tutor screen needs for ONE run: which project was tested, which
    error was injected, the user's own source lines it landed on, whether the project
    handled it correctly (tutor_needed=false) and, when it did not, a suggested code fix."""
    run = _owned_run(req, req.params["id"])
    key = req.headers.get("X-Gemini-Key") or req.headers.get("X-Api-Key") or req.headers.get("x-gemini-key") or req.headers.get("x-api-key")
    return 200, tutor_context.build_context(run, custom_api_key=key)


@router.get("/projects/{id}/latest-run")
def get_project_latest_run(req):
    """Newest run of this project (any status) plus the newest COMPLETED one. The Tutor
    polls this so every fresh run is picked up, not only the first."""
    project = _owned_project(req, req.params["id"])
    rows = db.get_many("experiment_runs", "project_id = ?", (project["id"],))
    rows = [r for r in rows if r.get("started_at") is not None] or rows
    latest = rows[0] if rows else None
    completed = next((r for r in rows if r.get("status") == "COMPLETED"), None)

    def slim(r):
        if not r:
            return None
        return {"id": r["id"], "status": r.get("status"), "outcome": r.get("outcome"),
                "experiment_id": r.get("experiment_id"), "started_at": r.get("started_at"),
                "finished_at": r.get("finished_at")}
    recent = [slim(r) for r in rows if r.get("status") == "COMPLETED"][:15]
    names = {}
    for r in recent:
        e = db.get_one("experiments", r["experiment_id"]) or {}
        names[r["id"]] = e.get("name")
        r["experiment_name"] = names.get(r["id"])
    latest_slim = slim(latest)
    if latest_slim and latest and latest.get("experiment_id"):
        exp_row = db.get_one("experiments", latest["experiment_id"]) or {}
        fault = exp_row.get("fault_type") or ""
        latest_slim["experiment_name"] = exp_row.get("name") or tutor_context.FAULT_LABEL.get(fault, fault)
        latest_slim["fault_type"] = fault
        latest_slim["fault_label"] = tutor_context.FAULT_LABEL.get(fault, exp_row.get("name") or fault)
    return 200, {"project_id": project["id"], "project_name": project.get("name"),
                 "latest": latest_slim, "latest_completed": slim(completed), "recent": recent}



@router.post("/projects/{id}/ide/test")
def ide_test(req):
    _owned_project(req, req.params["id"])
    analysis_rows = db.get_many("project_analysis", "project_id = ?", (req.params["id"],))
    if not analysis_rows:
        raise HTTPError(400, "analyze the project before running tests")
    from app import sandbox
    import pathlib
    project = _owned_project(req, req.params["id"])
    profile = _profile_from_analysis_row(analysis_rows[0])
    adapter = profile.get("adapter")
    ws = sandbox.make_workspace(project["storage_path"], "ide-test")
    try:
        base = pathlib.Path(project["storage_path"])
        if adapter and "python" in adapter:
            argv = _python_test_argv()
        elif adapter and "node" in adapter:
            argv = _node_test_argv(base)
        elif adapter == "java_cli":
            java_files = [p.relative_to(base).as_posix() for p in base.rglob("*.java") if ".git" not in p.parts and "node_modules" not in p.parts]
            if not java_files:
                raise HTTPError(400, "no Java source files found")
            argv = ["javac", *java_files]
        elif adapter == "c_cli":
            argv = ["gcc", profile.get("entrypoint"), "-fsyntax-only"]
        elif adapter == "cpp_cli":
            argv = ["g++", profile.get("entrypoint"), "-std=c++17", "-fsyntax-only"]
        elif adapter == "go_cli":
            argv = ["go", "test", "./..."]
        elif adapter == "rust_cli":
            argv = ["rustc", profile.get("entrypoint"), "--emit", "metadata"]
        else:
            raise HTTPError(400, f"No test adapter is configured for {profile.get('framework') or 'this project'}. Use Run for the selected file.")
        result = sandbox.run_in_sandbox(argv, ws, timeout=90)
        if adapter and "python" in adapter and "pytest" in argv and result.exit_code == 5 and not result.timed_out:
            result = _python_unittest_fallback(sandbox, ws, result)
        return 200, {"ok": result.exit_code == 0 and not result.timed_out, "exit_code": result.exit_code,
                      "stdout": result.stdout, "stderr": result.stderr, "duration_seconds": result.duration_seconds,
                      "net_isolated": result.net_isolated}
    except HTTPError:
        raise
    except Exception as e:
        raise HTTPError(400, str(e))
    finally:
        try: sandbox.destroy_workspace(ws)
        except Exception: pass

@router.post("/projects/{id}/ide/run")
def ide_run(req):
    """Run the selected source file/project as a one-shot CLI program.

    This is deliberately separate from Chaos Lab's long-running HTTP service
    runner. A selected Java/C/C++/Python/etc. file should be executable from
    the terminal even when Linux network namespaces are unavailable on a
    native Windows development machine.
    """
    project = _owned_project(req, req.params["id"])
    analysis_rows = db.get_many("project_analysis", "project_id = ?", (req.params["id"],))
    if not analysis_rows:
        raise HTTPError(400, "analyze the project before running it")
    from app import sandbox
    import shutil
    body = req.json() or {}
    selected = (body.get("path") or "").replace("\\", "/").lstrip("/")
    profile = _profile_from_analysis_row(analysis_rows[0])
    entry = selected or profile.get("entrypoint")
    if not entry:
        raise HTTPError(400, "no executable entrypoint detected")
    target, rel = _safe_project_file(project, entry)
    if not target.exists():
        raise HTTPError(404, "selected file not found")

    adapter = _adapter_for_path(rel, profile.get("adapter"), profile.get("framework"))
    ws = sandbox.make_workspace(project["storage_path"], "ide-run")
    try:
        argv, post_argv = _build_ide_commands(adapter, rel, target, ws)
        compile_result = None
        if argv is not None:
            compile_result = sandbox.run_in_sandbox(argv, ws, timeout=60)
            if compile_result.exit_code != 0 or compile_result.timed_out:
                return 200, {"ok": False, "mode": "compile", "path": rel,
                              "exit_code": compile_result.exit_code, "stdout": compile_result.stdout,
                              "stderr": compile_result.stderr, "duration_seconds": compile_result.duration_seconds,
                              "net_isolated": compile_result.net_isolated}
        # Optional program input (what the user would type at the terminal). Fed to
        # stdin so scripts that call input()/scanf/Scanner work in the IDE.
        stdin_text = body.get("stdin")
        if stdin_text is not None:
            if not isinstance(stdin_text, str):
                raise HTTPError(400, "stdin must be a string")
            if len(stdin_text.encode("utf-8", "ignore")) > 64 * 1024:
                raise HTTPError(400, "program input is limited to 64 KB")
            if stdin_text and not stdin_text.endswith("\n"):
                stdin_text += "\n"
        result = sandbox.run_in_sandbox(post_argv, ws, timeout=120, stdin_data=stdin_text if stdin_text else None)
        return 200, {"ok": result.exit_code == 0 and not result.timed_out, "mode": "run",
                      "path": rel, "adapter": adapter, "exit_code": result.exit_code,
                      "stdout": result.stdout, "stderr": result.stderr,
                      "duration_seconds": result.duration_seconds, "timed_out": result.timed_out,
                      "net_isolated": result.net_isolated}
    except FileNotFoundError as e:
        raise HTTPError(400, f"required runtime/compiler is not installed or not on PATH: {e}")
    except Exception as e:
        raise HTTPError(400, str(e))
    finally:
        try: sandbox.destroy_workspace(ws)
        except Exception: pass


def _python_test_argv():
    """pytest when it is installed in the backend's interpreter, otherwise the
    standard-library unittest runner, so the Cloud IDE Test button never fails
    with "No module named pytest" on a fresh install."""
    import importlib.util
    if importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest", "-q"]
    return [sys.executable, "-m", "unittest", "discover", "-v"]


def _python_unittest_fallback(sandbox, ws, pytest_result):
    """pytest exit code 5 means it collected nothing - but pytest only looks at
    test_*.py / *_test.py, while real projects often ship a unittest-style
    tests.py or test.py (e.g. Flask's microblog), which was reported as
    "no tests found". Try unittest discovery before giving up."""
    import re
    alt = sandbox.run_in_sandbox(
        [sys.executable, "-m", "unittest", "discover", "-p", "test*.py", "-v"], ws, timeout=90)
    ran = re.search(r"^Ran (\d+) tests?", (alt.stdout or "") + (alt.stderr or ""), re.M)
    return alt if ran and int(ran.group(1)) > 0 else pytest_result


def _node_test_argv(base):
    """`npm test`, with jest's --runInBand only when the project actually uses
    jest (it used to be appended for every project, which breaks mocha/vitest
    and friends), and a clear error for a missing/placeholder test script."""
    import json as _json
    import re
    try:
        scripts = (_json.loads((base / "package.json").read_text(encoding="utf-8")).get("scripts") or {})
    except (OSError, ValueError):
        raise HTTPError(400, "no readable package.json found - Test needs an npm project")
    script = scripts.get("test")
    if not isinstance(script, str) or not script.strip():
        raise HTTPError(400, 'package.json has no "test" script - add one (for example "jest" or "node --test") to use Test')
    if re.search(r"no test specified", script):
        raise HTTPError(400, 'package.json "test" is still the npm-init placeholder ("no test specified") - replace it with a real test command')
    if not (base / "node_modules").is_dir():
        raise HTTPError(400, f"the project's dependencies are not installed (no node_modules folder). "
                             f"Run `npm install` in {base} first, then try Test again")
    argv = ["npm", "test"]
    if re.search(r"\bjest\b", script) and "runInBand" not in script and not re.search(r"(^|\s)(-i|--runInBand)\b", script):
        argv += ["--", "--runInBand"]
    return argv


def _adapter_for_path(rel, detected, framework=None):
    ext = pathlib.Path(rel).suffix.lower()
    return {
        ".py": "python_cli", ".js": "node_cli", ".java": "java_cli",
        ".c": "c_cli", ".cpp": "cpp_cli", ".cc": "cpp_cli", ".cxx": "cpp_cli",
        ".go": "go_cli", ".rs": "rust_cli", ".kt": "kotlin_cli",
        ".php": "php_cli", ".rb": "ruby_cli",
        ".sh": "shell_cli", ".bash": "shell_cli", ".ps1": "powershell_cli", ".bat": "batch_cli", ".cmd": "batch_cli",
    }.get(ext, detected or "unknown")


def _build_ide_commands(adapter, rel, target, ws):
    p = pathlib.Path(rel)
    rel_norm = p.as_posix()
    if adapter == "python_cli": return None, [sys.executable, rel_norm]
    if adapter in ("node_cli", "node_generic"): return None, ["node", rel_norm]
    if adapter == "php_cli": return None, ["php", rel_norm]
    if adapter == "ruby_cli": return None, ["ruby", rel_norm]
    if adapter == "go_cli": return None, ["go", "run", rel_norm]
    if adapter == "shell_cli": return None, ["bash", rel_norm]
    if adapter == "powershell_cli": return None, ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", rel_norm]
    if adapter == "batch_cli": return None, ["cmd", "/c", rel_norm]
    if adapter == "rust_cli": return ["rustc", rel_norm, "-o", ".chaos_ide_bin.exe"], ["./.chaos_ide_bin.exe"]
    if adapter == "c_cli": return ["gcc", rel_norm, "-O0", "-o", ".chaos_ide_bin.exe"], ["./.chaos_ide_bin.exe"]
    if adapter == "cpp_cli": return ["g++", rel_norm, "-O0", "-std=c++17", "-o", ".chaos_ide_bin.exe"], ["./.chaos_ide_bin.exe"]
    if adapter == "kotlin_cli": return ["kotlinc", rel_norm, "-include-runtime", "-d", ".chaos_ide_bin.jar"], ["java", "-jar", ".chaos_ide_bin.jar"]
    if adapter == "java_cli":
        source = target.read_text(encoding="utf-8", errors="ignore")
        package_match = re.search(r"^\s*package\s+([A-Za-z_][\w.]*)\s*;", source, re.M)
        class_name = p.stem
        fqcn = f"{package_match.group(1)}.{class_name}" if package_match else class_name
        if package_match:
            # Compile package classes into the workspace root so the JVM classpath
            # is stable regardless of where the source file lives.
            return ["javac", "-d", ".", rel_norm], ["java", "-cp", ".", fqcn]
        return ["javac", rel_norm], ["java", "-cp", p.parent.as_posix() if p.parent.as_posix() != "." else ".", class_name]
    raise HTTPError(400, f"Cloud IDE cannot execute files of type '{p.suffix or 'unknown'}' yet")


def _profile_from_analysis_row(row):
    entrypoint_data = db.loads(row["entrypoint_json"])
    return {
        "framework": row["framework"],
        "execution_status": row["execution_status"],
        "execution_status_reason": entrypoint_data.get("reason"),
        "components": db.loads(row["components_json"]),
        "entrypoint": entrypoint_data["entrypoint"],
        "adapter": entrypoint_data["adapter"],
    }
