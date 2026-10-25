# One-time local setup: create the Jarvis Python runtime and install dependencies.
# The desktop app, Launch-Jarvis.cmd and scripts/build_desktop.ps1 all use the
# runtime this script creates at %LOCALAPPDATA%\Jarvis\runtime.
#
# Usage:
#   powershell -File scripts\setup_local.ps1            # engine + desktop dependencies
#   powershell -File scripts\setup_local.ps1 -Voice     # also install the optional personal-voice engine
param([switch]$Voice)
$ErrorActionPreference = "Stop"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $env:LOCALAPPDATA "Jarvis\runtime"

# Finds Python 3.11 and sets $PythonExe/$PythonArgs to invoke it.
function Find-Python311 {
    foreach ($name in @("py", "python")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        foreach ($versionArgs in @(@("-3.11"), @())) {
            & $command.Source @versionArgs -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) {
                $script:PythonExe = $command.Source
                $script:PythonArgs = $versionArgs
                return
            }
        }
    }
    # A just-installed Python is often not on the current terminal's PATH yet.
    foreach ($fixed in @(
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher\py.exe"),
            "C:\Program Files\Python311\python.exe",
            "C:\Program Files (x86)\Python311\python.exe")) {
        if (-not (Test-Path -LiteralPath $fixed)) { continue }
        $versionArgs = @(); if ($fixed -like "*py.exe") { $versionArgs = @("-3.11") }
        & $fixed @versionArgs -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $script:PythonExe = $fixed
            $script:PythonArgs = $versionArgs
            return
        }
    }
    throw "Python 3.11 was not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this script again."
}

if (Test-Path -LiteralPath (Join-Path $Runtime "Scripts\python.exe")) {
    Write-Host "Using the existing runtime at $Runtime" -ForegroundColor Green
    $PythonExe = Join-Path $Runtime "Scripts\python.exe"
    $PythonArgs = @()
} else {
    Find-Python311
    Write-Host "Creating the Jarvis runtime at $Runtime (this can take a minute)..."
    New-Item -ItemType Directory -Force -Path (Split-Path $Runtime) | Out-Null
    & $PythonExe @PythonArgs -m venv $Runtime
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python runtime." }
    $PythonExe = Join-Path $Runtime "Scripts\python.exe"
    $PythonArgs = @()
}

& $PythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not update pip." }
& $PythonExe -m pip install -r (Join-Path $Project "Requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Installing Jarvis dependencies failed. Check your internet connection and try again." }

if ($Voice) {
    & $PythonExe -m pip install -r (Join-Path $Project "Requirements.voice.txt")
    if ($LASTEXITCODE -ne 0) { throw "Installing the optional personal-voice engine failed." }
}

Write-Host ""
Write-Host "The Jarvis runtime is ready: $Runtime" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Download the local speech and chat models (about 1.3 GB, one time):"
Write-Host "       & `"$PythonExe`" -X utf8 `"$Project\scripts\download_models.py`""
Write-Host "     Or start Jarvis and use Settings > Download speech & chat models."
Write-Host "  2. Launch the desktop assistant:"
Write-Host "       $Project\Launch-Jarvis.cmd"
Write-Host "     Or from source:  & `"$PythonExe`" `"$Project\Main.py`""
