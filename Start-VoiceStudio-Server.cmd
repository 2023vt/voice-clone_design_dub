@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 goto launch_error

set "VS_PYTHON=.venv\Scripts\python.exe"
if not exist "%VS_PYTHON%" goto missing_dependencies
"%VS_PYTHON%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 goto missing_dependencies

set "VS_HOST=127.0.0.1"
if /i "%~1"=="--lan" goto lan_mode
if /i "%~1"=="--check" exit /b 0
if not "%~1"=="" goto usage
goto start_server

:lan_mode
if not "%~2"=="" goto usage
if not defined OMNIVOICE_API_KEY goto missing_key
set "VS_HOST=0.0.0.0"
set "OMNIVOICE_SERVER_MODE=1"

:start_server
echo Starting VoiceStudio API server on %VS_HOST%:3900...
echo No desktop window will open. Press Ctrl+C to stop.
"%VS_PYTHON%" -m uvicorn main:app --app-dir backend --host %VS_HOST% --port 3900
if errorlevel 1 goto launch_error
exit /b 0

:missing_dependencies
echo VoiceStudio backend setup is incomplete. Run bun run setup:api once.
pause
exit /b 1

:missing_key
echo LAN mode requires OMNIVOICE_API_KEY in this terminal's environment.
echo Set a strong key, then run Start-VoiceStudio-Server.cmd --lan again.
pause
exit /b 1

:usage
echo Usage: Start-VoiceStudio-Server.cmd [--lan]
echo Default: local API on 127.0.0.1:3900, no API key required.
echo --lan: API on all interfaces; OMNIVOICE_API_KEY must be set first.
exit /b 2

:launch_error
echo VoiceStudio API server could not start. See the error above.
pause
exit /b 1
