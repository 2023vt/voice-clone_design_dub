@echo off
title VoiceStudio (custom build)
rem Customised VoiceStudio: this folder's UI *and* backend, run with the Python
rem runtime the installed app already set up (no new downloads). Same voices,
rem history and models as the installed app.

if "%VS_PORT%"=="" set "VS_PORT=3900"
set "VS_PY=%APPDATA%\VoiceStudio\runtime\project\.venv\Scripts\python.exe"

if not exist "%VS_PY%" (
  echo VoiceStudio runtime not found. Install and open VoiceStudio once, then try again.
  pause
  exit /b 1
)

powershell -NoProfile -Command "try { Invoke-WebRequest http://127.0.0.1:%VS_PORT%/health -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  echo The installed VoiceStudio is still running on port %VS_PORT%.
  echo Quit it ^(tray icon ^> Quit^), then run this launcher again.
  pause
  exit /b 1
)

rem GPU: this PC has two NVIDIA cards. In PCI-bus order GPU 0 = RTX 5080 (ComfyUI,
rem LoRA training), GPU 1 = RTX 5060 Ti (always-on voice). VoiceStudio runs on GPU 1.
rem Switch back: "set VS_GPU=0" before running this file (or edit the line below).
rem "set VS_GPU=auto" leaves the choice to Settings -> CUDA adapter in the app.
if "%VS_GPU%"=="" set "VS_GPU=1"
if /i not "%VS_GPU%"=="auto" (
  set "CUDA_DEVICE_ORDER=PCI_BUS_ID"
  set "CUDA_VISIBLE_DEVICES=%VS_GPU%"
)

set "OMNIVOICE_PORT=%VS_PORT%"
set "OMNIVOICE_BACKEND_CMD=%VS_PY% -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port %VS_PORT%"

echo Starting customised VoiceStudio...
cd /d "%~dp0electron"
bun run dev
