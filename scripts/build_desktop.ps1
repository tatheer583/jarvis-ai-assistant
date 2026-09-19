$ErrorActionPreference = "Stop"
$Project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $env:LOCALAPPDATA "Jarvis/runtime/Scripts/python.exe"
$BuildRoot = Join-Path $env:LOCALAPPDATA "Jarvis/build/frontend"
$Target = Join-Path $env:LOCALAPPDATA "Jarvis/build/target"
if (-not (Test-Path -LiteralPath $Python)) { throw "Local Python runtime missing. See desktop/README.md." }
Push-Location $Project
try {
    & $Python -B -m unittest discover -s scripts/tests -q
    if ($LASTEXITCODE -ne 0) { throw "Python validation failed." }
    & $Python -B (Join-Path $Project "scripts/smoke_engine.py")
    if ($LASTEXITCODE -ne 0) { throw "Source engine smoke check failed." }
    & $Python -m PyInstaller --noconfirm (Join-Path $Project "jarvis-engine.spec")
    if ($LASTEXITCODE -ne 0) { throw "Offline engine packaging failed." }
    & $Python (Join-Path $Project "scripts/sync_desktop.py")
    if ($LASTEXITCODE -ne 0) { throw "Desktop source synchronization failed." }
    $env:PATH = (Join-Path $env:USERPROFILE ".rustup/toolchains/stable-x86_64-pc-windows-msvc/bin") + ";" + $env:PATH
    $env:CARGO_TARGET_DIR = $Target
    $env:JARVIS_PROJECT_DIR = $Project
    Push-Location $BuildRoot
    try {
        # Lockfile-controlled install; use the package cache when possible.
        npm.cmd ci --prefer-offline --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        npm.cmd test
        if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed." }
        npm.cmd run tauri -- build --no-bundle
        if ($LASTEXITCODE -ne 0) { throw "Tauri build failed." }
    } finally { Pop-Location }
    & $Python -B (Join-Path $Project "scripts/smoke_engine.py") --executable (Join-Path $Project "dist/jarvis-engine/jarvis-engine.exe")
    if ($LASTEXITCODE -ne 0) { throw "Packaged engine smoke check failed; original release preserved." }
    & $Python (Join-Path $Project "scripts/stage_desktop.py")
    if ($LASTEXITCODE -ne 0) { throw "Application staging failed." }
} finally { Pop-Location }
