from __future__ import annotations
"""Firebase ID-token authentication with a safe local-development fallback.

Set FIREBASE_AUTH_REQUIRED=true in production. Firebase Admin SDK is loaded
lazily so the core test suite can run without cloud credentials.
"""
import hmac
import json
import os

from app.http_framework import HTTPError

_admin = None
_init_error = None


def _firebase_enabled() -> bool:
    return os.environ.get("FIREBASE_AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"} or bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")) or bool(os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")) or bool(_default_key_file())


_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_have_service_account = False


def _default_key_file() -> str | None:
    """A service-account key dropped next to the backend is picked up automatically,
    so no environment variable has to be set in every new terminal window."""
    for name in ("firebase-service-account.json", "serviceAccountKey.json"):
        path = os.path.join(_BACKEND_DIR, name)
        if os.path.isfile(path):
            return path
    return None


def _read_env_file_value(path: str, key: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None


def _discover_project_id(frontend_dir: str | None = None) -> str | None:
    """Firebase project id (not a secret). Token verification only needs this, not a key.
    Order: env vars, then the frontend's own VITE_FIREBASE_PROJECT_ID in chaos/.env."""
    for name in ("FIREBASE_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    fdir = frontend_dir or os.path.join(os.path.dirname(_BACKEND_DIR), "chaos")
    for fname in (".env.local", ".env"):
        val = _read_env_file_value(os.path.join(fdir, fname), "VITE_FIREBASE_PROJECT_ID")
        if val:
            return val
    return None


def firebase_admin_available() -> bool:
    global _admin, _init_error, _have_service_account
    if _admin is not None:
        return True
    if _init_error is not None:
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials

        class _ProjectOnlyCredentials(credentials.Base):
            """Credential provider for verifying Firebase ID tokens without Google Cloud ADC.
            Token verification only needs Google's public certificates (OIDC), not service account
            credentials. AnonymousCredentials satisfies the internal firebase-admin Client requirement."""
            def get_credential(self):
                try:
                    import google.auth.credentials
                    return google.auth.credentials.AnonymousCredentials()
                except Exception:
                    return None

        if not firebase_admin._apps:
            raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
            key_file = _default_key_file()
            options = {"storageBucket": os.environ.get("FIREBASE_STORAGE_BUCKET") or None}
            project_id = _discover_project_id()
            if project_id:
                options["projectId"] = project_id
            if raw:
                cred = credentials.Certificate(json.loads(raw))
                _have_service_account = True
            elif key_file:
                cred = credentials.Certificate(key_file)
                _have_service_account = True
            elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                try:
                    c = credentials.ApplicationDefault()
                    c.get_credential()
                    cred = c
                    _have_service_account = True
                except Exception:
                    cred = _ProjectOnlyCredentials()
            else:
                # No service account key: ID tokens can still be verified (signature/audience/issuer are checked
                # against Google's public certificates) as long as the project id is known.
                # Use AnonymousCredentials if Google Cloud ADC is not installed locally.
                try:
                    c = credentials.ApplicationDefault()
                    c.get_credential()
                    cred = c
                    _have_service_account = True
                except Exception:
                    cred = _ProjectOnlyCredentials()
            firebase_admin.initialize_app(cred, options)
        _admin = firebase_admin
        return True
    except Exception as exc:
        _init_error = str(exc)
        return False


def _backend_project_id() -> str:
    try:
        import firebase_admin
        return firebase_admin.get_app().project_id or _discover_project_id() or "unknown"
    except Exception:
        return _discover_project_id() or "unknown"


def _explain_verify_failure(exc: Exception) -> tuple[str, str]:
    """Map a verify_id_token failure to (log reason, short client hint).

    The hint is deliberately generic (no project ids or token contents)."""
    name = type(exc).__name__
    msg = str(exc).lower()
    if "project id is required" in msg:
        return "no Firebase project", "backend has no Firebase project id (see backend console)"
    if "defaultcredentialserror" in name.lower() or "default credentials" in msg:
        return "adc missing", "backend missing Google credentials (set service account or project id)"
    if name == "ExpiredIdTokenError":
        return "expired token", "token expired, sign in again"
    if name == "RevokedIdTokenError":
        return "revoked token", "session revoked, sign out and sign in again"
    if "audience" in msg or "issuer" in msg or 'incorrect "aud"' in msg or 'incorrect "iss"' in msg:
        return "project mismatch", "frontend and backend use different Firebase projects"
    if "too early" in msg or "clock" in msg:
        return "clock skew", "system clock is out of sync"
    if name in {"CertificateFetchError", "TransportError", "ConnectionError"} or "connection" in msg or "max retries" in msg or "ssl" in msg:
        return "cannot reach Google", "backend cannot reach Google to verify the token"
    if "segments" in msg or "decoding" in msg or "signature" in msg or "parse segment" in msg:
        return "not a Firebase ID token", "Authorization header is not a Firebase ID token (check VITE_API_TOKEN)"
    return "unknown", "see backend console for details"


def verify_bearer(header: str) -> dict:
    if not header.startswith("Bearer "):
        raise HTTPError(401, "Firebase authentication required")
    token = header[7:].strip()
    if not token:
        raise HTTPError(401, "Firebase authentication required")
    if not firebase_admin_available():
        raise HTTPError(503, "Firebase authentication is not configured on the backend")
    try:
        from firebase_admin import auth
        return auth.verify_id_token(token, check_revoked=_have_service_account)
    except Exception as exc:
        reason, hint = _explain_verify_failure(exc)
        # Log the real cause on the backend console (never the token itself).
        print(f"[auth] Firebase token rejected: {type(exc).__name__}: {exc}", flush=True)
        print(f"[auth] backend Firebase project = {_backend_project_id()}  ({reason})", flush=True)
        raise HTTPError(401, f"invalid or expired Firebase ID token - {hint}")


def authenticate_request(req, public: bool = False) -> str:
    """Attach req.user_uid and return the actor identity."""
    if public:
        req.user_uid = None
        req.actor = "anonymous"
        return "anonymous"

    auth_header = req.headers.get("Authorization", "")
    api_token = os.environ.get("CHAOS_TUTOR_API_TOKEN", "")
    if api_token and hmac.compare_digest(auth_header.encode(), f"Bearer {api_token}".encode()) and not _firebase_enabled():
        req.user_uid = None
        req.actor = "api-token"
        return "api-token"

    if _firebase_enabled() or (auth_header.startswith("Bearer ") and auth_header[7:] and auth_header != f"Bearer {api_token}"):
        decoded = verify_bearer(auth_header)
        uid = decoded.get("uid")
        if not uid:
            raise HTTPError(401, "Firebase token has no user identity")
        req.user_uid = uid
        req.actor = uid
        return uid

    if api_token:
        raise HTTPError(401, "authentication required")

    # Local development mode: no cloud auth configured. This is deliberately
    # disabled by FIREBASE_AUTH_REQUIRED=true in production.
    req.user_uid = "local"
    req.actor = "local"
    return "local"


def firestore_enabled() -> bool:
    if not _firebase_enabled() or not _have_service_account:
        return False
    return firebase_admin_available() and os.environ.get("FIREBASE_SYNC_FIRESTORE", "true").lower() in {"1", "true", "yes", "on"}


def sync_project(project: dict) -> None:
    if not project.get("owner_uid") or project["owner_uid"] == "local" or not _firebase_enabled() or not _have_service_account:
        return
    if not firestore_enabled():
        return
    try:
        from firebase_admin import firestore
        firestore.client().document(f"users/{project['owner_uid']}/projects/{project['id']}").set({
            "projectId": project["id"],
            "name": project["name"],
            "status": project["status"],
            "createdAt": project["created_at"],
        }, merge=True)
    except Exception:
        # Cloud sync must never corrupt or block the authoritative SQLite state.
        pass


def upload_archive(project: dict, archive_path: str) -> None:
    if not project.get("owner_uid") or project["owner_uid"] == "local" or not _firebase_enabled() or not _have_service_account:
        return
    if not firebase_admin_available() or os.environ.get("FIREBASE_SYNC_STORAGE", "false").lower() not in {"1", "true", "yes", "on"}:
        return
    try:
        from firebase_admin import storage
        bucket = storage.bucket()
        blob = bucket.blob(f"users/{project['owner_uid']}/projects/{project['id']}/source.zip")
        blob.upload_from_filename(archive_path, content_type="application/zip")
    except Exception:
        pass
