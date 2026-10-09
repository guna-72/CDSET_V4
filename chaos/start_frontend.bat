@echo off
REM Starts the web app (installs packages the first time).
cd /d "%~dp0"
if not exist node_modules call npm install
call npm run dev
