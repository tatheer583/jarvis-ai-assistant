@echo off

setlocal

set "JARVIS_PHASE1=%~dp0artifacts\staging\Jarvis-20260916-161017\jarvis-desktop.exe"

if not exist "%JARVIS_PHASE1%" (

  echo The verified Phase 1 build is missing. See desktop\README.md.

  exit /b 1

)

start "" "%JARVIS_PHASE1%"

exit /b 0

