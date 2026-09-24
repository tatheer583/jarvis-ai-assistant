@echo off
setlocal
set "JARVIS_APP=%~dp0artifacts\Jarvis\jarvis-desktop.exe"
if exist "%JARVIS_APP%" (
  start "" "%JARVIS_APP%"
  exit /b 0
)
set "JARVIS_APP=%~dp0desktop\src-tauri\target\release\jarvis-desktop.exe"
if exist "%JARVIS_APP%" (
  start "" "%JARVIS_APP%"
  exit /b 0
)
set "JARVIS_PYTHON=%LOCALAPPDATA%\Jarvis\runtime\Scripts\pythonw.exe"
if exist "%JARVIS_PYTHON%" (
  start "" "%JARVIS_PYTHON%" "%~dp0Main.py"
  exit /b 0
)
echo Jarvis is not built yet. Run scripts\build_desktop.ps1 first.
pause
exit /b 1
