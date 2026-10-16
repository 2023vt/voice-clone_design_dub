@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 goto launch_error

rem Use an installed Node 22+; this machine also has a bundled Node 24 runtime.
set "NODE_EXE=node"
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" >nul 2>&1
if not errorlevel 1 goto node_ready
set "NODE_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "%NODE_EXE%" goto missing_node
"%NODE_EXE%" -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" >nul 2>&1
if errorlevel 1 goto missing_node

:node_ready
if not exist "electron\node_modules\electron-vite\package.json" goto missing_dependencies
if not exist ".venv\Scripts\python.exe" goto missing_dependencies
if /i "%~1"=="--check" exit /b 0

echo Starting VoiceStudio...
"%NODE_EXE%" "electron\scripts\dev.mjs"
if errorlevel 1 goto launch_error
exit /b 0

:missing_node
echo VoiceStudio needs Node.js 22 or newer. Install it, then double-click this file again.
pause
exit /b 1

:missing_dependencies
echo VoiceStudio setup is incomplete. Run bun install and bun run setup:api once.
pause
exit /b 1

:launch_error
echo VoiceStudio could not start. See the error above.
pause
exit /b 1
