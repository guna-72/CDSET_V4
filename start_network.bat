@echo off
REM start_network.bat
REM Launches Chaos Tutor in Network Mode so any device (phones, tablets, laptops)
REM on the same local network / Wi-Fi can access the web interface and API.
REM Services run in the background (tracked in logs\running_pids.txt).
REM Cleanly stop anytime by running "Stop ChaosTutor.vbs" or pressing 'Q' here.

setlocal enabledelayedexpansion
cd /d "%~dp0"
title Chaos Tutor - Network Mode

REM 1. Detect LAN IPv4 Address
set "LAN_IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i /c:"IPv4 Address" /c:"IP Address"') do (
    if not defined LAN_IP (
        set "temp_ip=%%a"
        set "temp_ip=!temp_ip: =!"
        if not "!temp_ip!"=="" (
            if not "!temp_ip:~0,4!"=="127." (
                if not "!temp_ip:~0,8!"=="169.254." (
                    set "LAN_IP=!temp_ip!"
                )
            )
        )
    )
)
if "%LAN_IP%"=="" set "LAN_IP=127.0.0.1"

REM 2. Configure network environment variables
set "HOST=0.0.0.0"
set "CHAOS_TUTOR_CORS_ORIGINS=*"

REM 3. Launch the background services via VBS launcher
start "" wscript.exe "%~dp0Start ChaosTutor Network.vbs" /nomsg /nobrowser

REM 4. Display banner and network information
cls
echo ==============================================================================
echo                       CHAOS TUTOR - NETWORK MODE
echo ==============================================================================
echo.
echo   All Chaos Tutor services are running in the background.
echo.
echo   [1] Local access (on this computer):
echo       http://localhost:5173
echo.
echo   [2] Network access (phones, tablets, other PCs on same Wi-Fi / LAN):
echo       http://%LAN_IP%:5173
echo.
echo   [3] Backend API:
echo       http://%LAN_IP%:8090
echo.
echo   [4] AI Tutor Module:
echo       http://%LAN_IP%:5000
echo.
echo ==============================================================================
echo   Tips:
echo   - Connect your mobile or other device to the SAME Wi-Fi or LAN network.
echo   - Open the browser on that device and go to: http://%LAN_IP%:5173
echo   - If other devices cannot reach the page, verify that your Windows network
echo     profile is set to 'Private' and Windows Defender Firewall allows Node/Python.
echo   - Real-time logs are saved in the 'logs' folder.
echo ==============================================================================
echo.
echo   Options:
echo     [Q] Stop Chaos Tutor services and exit
echo     [O] Open browser to Network URL (http://%LAN_IP%:5173)
echo     [C] Close this window (services will stay running in background)
echo.

:menu_loop
choice /c QOC /n /m "Select an option [Q = Stop, O = Open in Browser, C = Close window]: "
if errorlevel 3 goto :close_window
if errorlevel 2 goto :open_browser
if errorlevel 1 goto :stop_services
goto :menu_loop

:open_browser
start "" "http://%LAN_IP%:5173"
goto :menu_loop

:stop_services
echo.
echo Stopping Chaos Tutor services...
start "" wscript.exe "%~dp0Stop ChaosTutor.vbs" /nomsg
ping -n 3 127.0.0.1 >nul
echo Chaos Tutor services stopped.
ping -n 2 127.0.0.1 >nul
exit

:close_window
exit
