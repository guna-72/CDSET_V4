@echo off
cd /d "%~dp0"
set "PY_CMD=python"
python --version >nul 2>&1 || set "PY_CMD=py"
%PY_CMD% -c "import flask" >nul 2>&1 || %PY_CMD% -m pip install -r requirements.txt
%PY_CMD% app.py
