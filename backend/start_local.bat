@echo off
REM Starts the backend in LOCAL mode (static API token, no Firebase).
REM Usage: start_local.bat [token]     (default token: local-dev-token)
REM The SAME token must be in chaos\.env as VITE_API_TOKEN.
setlocal
set "TOKEN=%~1"
if "%TOKEN%"=="" set "TOKEN=local-dev-token"

REM Clear anything that would switch the backend into Firebase mode.
set "GOOGLE_APPLICATION_CREDENTIALS="
set "FIREBASE_SERVICE_ACCOUNT_JSON="
set "FIREBASE_AUTH_REQUIRED=false"

set "CHAOS_TUTOR_API_TOKEN=%TOKEN%"
REM Windows runs in degraded sandbox mode by default (no Administrator needed).
set "HOST=127.0.0.1"
set "BACKEND_PORT=8090"

echo Starting backend in LOCAL mode. Token: %TOKEN%
echo Expect the line:  Auth: LOCAL mode
set "PY_CMD=python"
python --version >nul 2>&1 || set "PY_CMD=py"
%PY_CMD% -m app.main
endlocal
