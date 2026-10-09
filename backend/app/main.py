from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, llm_providers
from app.api import router
from app.http_framework import make_server

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("BACKEND_PORT", "8090"))


def main():
    db.init_db()
    server = make_server(router, HOST, PORT)
    print(f"Chaos Tutor MVP backend listening on http://{HOST}:{PORT}", flush=True)
    _print_llm_status()
    _print_auth_status()
    _print_sandbox_status()
    server.serve_forever()


def _print_auth_status():
    """Tell the operator up front which auth mode is active (avoids silent 401s)."""
    from app import auth
    pid = auth._discover_project_id()
    if auth._firebase_enabled() or pid:
        if auth.firebase_admin_available():
            has_key = auth._have_service_account
            print(f"Auth: Firebase ON - project = {auth._backend_project_id()} "
                  f"({'service account found' if has_key else 'project id only: tokens are verified, revocation checks off'}). "
                  "Must equal VITE_FIREBASE_PROJECT_ID in chaos/.env", flush=True)
        else:
            print(f"Auth: Firebase configured but the Admin SDK failed to initialise: {auth._init_error}", flush=True)
    else:
        print("Auth: LOCAL mode (no Firebase project found). "
              "A logged-in Firebase frontend will fail; remove VITE_FIREBASE_* for offline use.", flush=True)


def _print_sandbox_status():
    """Say up front whether service-based chaos tests can run on this machine."""
    try:
        from app import sandbox
        from app.config import ALLOW_DEGRADED_SANDBOX
        if sandbox.network_isolation_available():
            print("Sandbox: network isolation AVAILABLE - service tests will run isolated.", flush=True)
        elif ALLOW_DEGRADED_SANDBOX:
            print("Sandbox: DEGRADED mode (normal on Windows without Administrator) - service tests run "
                  "WITHOUT network isolation. Only import projects you trust. "
                  "For strict isolation run as Administrator or use WSL2.", flush=True)
        else:
            print("Sandbox: network isolation UNAVAILABLE and degraded mode is OFF - HTTP/service tests "
                  "will show 'Blocked by safety'. Run as Administrator / use WSL2, or set "
                  "CHAOS_TUTOR_ALLOW_DEGRADED_SANDBOX=true for trusted local demos.", flush=True)
    except Exception as exc:
        print(f"Sandbox: status check failed: {exc}", flush=True)


def _print_llm_status():
    """Printed on every startup so LLM spend is never silently on — see
    app/llm_providers.py:diagnosis_enabled for the actual gate."""
    keys_present = llm_providers.any_keys_configured()
    enabled = llm_providers.explicitly_enabled()
    if keys_present and enabled:
        providers = ", ".join(llm_providers.configured_providers())
        print(f"AI diagnosis: ON — will call out to: {providers} (rotating across all configured keys)", flush=True)
    elif keys_present and not enabled:
        print("AI diagnosis: OFF (rule-based only) — provider keys are configured but "
              "ENABLE_LLM_DIAGNOSIS is not set, so no spend will occur. "
              "Set ENABLE_LLM_DIAGNOSIS=true to turn it on.", flush=True)
    else:
        print("AI diagnosis: OFF (rule-based only) — no provider keys configured.", flush=True)


if __name__ == "__main__":
    main()
