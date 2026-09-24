@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run scripts\setup.ps1 first.
  exit /b 1
)
".venv\Scripts\python.exe" -m voicepilot --config ".\config.yaml" --stop
if errorlevel 1 (
  echo Winsper did not respond to a clean stop request.
  exit /b 1
)
echo Winsper stopped.
