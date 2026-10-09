@echo off
REM start_windows.bat
REM Compatibility wrapper: launches Chaos Tutor with no Administrator
REM prompt and no visible console windows (same as double-clicking
REM "Start ChaosTutor.vbs" directly). This window closes itself
REM immediately after handing off.
cd /d "%~dp0"
start "" wscript.exe "%~dp0Start ChaosTutor.vbs"
exit
