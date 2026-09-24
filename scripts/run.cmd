@echo off
setlocal

set "APP_ROOT=%~dp0.."
pushd "%APP_ROOT%" >nul

if not exist ".\.venv\Scripts\python.exe" (
  echo Virtual environment not found. Run scripts\setup.ps1 first.
  popd >nul
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build-native-audio.ps1" -Quiet
if errorlevel 1 (
  echo Could not prepare Winsper's Windows microphone component.
  popd >nul
  exit /b 1
)
set "WINSPER_NATIVE_AUDIO_DLL=%APP_ROOT%\build\native-audio\winsper_audio.dll"

".\.venv\Scripts\python.exe" -m voicepilot --config ".\config.yaml" %*
set "EXIT_CODE=%ERRORLEVEL%"

popd >nul
exit /b %EXIT_CODE%
