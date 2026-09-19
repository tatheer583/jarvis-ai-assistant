# Jarvis Desktop

The Tauri/React UI uses the local Python engine through Rust-managed stdin/stdout JSON lines. It needs no cloud credentials.

## Launch

`Launch-Jarvis.cmd` starts the preserved release in `artifacts/Jarvis`. Keep the executable and its complete `engine` folder together. A new build is staged separately until its launch is verified.

Ctrl+Alt+J activates voice. Ctrl+Alt+Esc requests cancellation, clears pending confirmations/grid mode, stops speech and pauses the microphone. Cancellation is cooperative: already completed effects stay applied, and some native calls cannot be interrupted mid-call.

## Build requirements

Use Windows, Python 3.11 with `Requirements.txt` plus PyInstaller, Node/npm, Rust stable MSVC, Visual Studio C++ build tools and WebView2. These tools were already present in the inspected environment; the build script does not silently install system tools. The existing source and package lockfiles remain authoritative. No new Python/npm/Cargo dependency was added for Phase 1.

The script expects Python at `%LOCALAPPDATA%\Jarvis\runtime\Scripts\python.exe`. It synchronizes repository sources into the existing local build cache outside OneDrive, performs the tests, packages Python, builds Tauri and writes a new timestamped directory under `artifacts/staging`.

```powershell
powershell -File scripts/build_desktop.ps1
```

The source manifest and executable SHA-256 hashes are written to `build-manifest.json`. Staging preserves `artifacts/Jarvis` and the original launcher. Dependencies/model setup may require internet; runtime core commands do not.

## Validate a build

```powershell
& "$env:LOCALAPPDATA\Jarvis\runtime\Scripts\python.exe" -B scripts/smoke_engine.py
& "$env:LOCALAPPDATA\Jarvis\runtime\Scripts\python.exe" -B scripts/smoke_engine.py --executable "artifacts/staging/<build>/engine/jarvis-engine.exe"
```

The smoke check creates a temporary empty profile, disables audio, validates startup and multilingual UTF-8 IPC even with a legacy Windows code page, runs a local time command, requests emergency stop and checks clean shutdown. It does not test real speech recognition, desktop side effects or the physical keyboard shortcut.

Then launch the staged `jarvis-desktop.exe` and inspect engine connection, controls and settings. Windows application-control rejection is a failed launch check; do not disable OS protection or promote an unverified package.

## Data and status

The original settings, models and `jarvis.sqlite3` live in `%LOCALAPPDATA%\Jarvis`; `JARVIS_DATA_DIR` can isolate a test profile. Schema 0 settings migrate on the next successful save. Invalid/future settings remain intact and automatic listening is disabled.

Audit metadata is separate at `audit/events.sqlite3`. Retention defaults to 90 days; cleanup runs on the next audit startup after changing retention. Existing conversation history is not an encrypted secret store.

The UI truthfully reports local control with owner authentication unconfigured. The provider remains local; optional online contracts have no production adapter yet. The camera and remote approval have no active subsystem or fake enable switches.

Whisper and Qwen load locally when requested. Optional reference voice synthesis uses the existing separate local Python worker; its heavyweight packages are excluded from the engine bundle. A packaged build therefore needs that separately configured runtime for this optional voice mode.

Verified Phase 1 build: run `Launch-Jarvis-Phase1.cmd`. See [validation report](../docs/phase1-validation.md).
