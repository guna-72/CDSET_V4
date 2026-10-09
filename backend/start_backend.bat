@echo off
REM Starts the backend normally (any Windows terminal, no Administrator needed).
REM Uses whatever auth settings are already in this window's environment.
cd /d "%~dp0"
set "PY_CMD=python"
python --version >nul 2>&1 || set "PY_CMD=py"
if "%CHAOS_TUTOR_API_TOKEN%"=="" set "CHAOS_TUTOR_API_TOKEN=local-dev-token"
%PY_CMD% -c "import firebase_admin, dotenv, google.genai" >nul 2>&1 || %PY_CMD% -m pip install -r requirements.txt
%PY_CMD% -m app.main

