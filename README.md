# Jarvis Local Desktop

Jarvis is an existing Windows desktop assistant built with Tauri, React, TypeScript and a local Python engine. Core commands do not require an API key. Local Whisper speech recognition and local Qwen chat need their model files installed first.

Launch the existing packaged release with `Launch-Jarvis.cmd`. Keep its `engine` directory beside `jarvis-desktop.exe`. See [desktop/README.md](desktop/README.md) for building and testing a staged release.

## Implemented capabilities

- Voice activation and typed commands; Ctrl+Alt+J activates listening.
- Applications, keyboard shortcuts, typing, mouse, mouse grid, windows and volume.
- Create, copy, move, rename and recycle files; destructive commands request confirmation.
- Filename search, local notes, one-time reminders and activity history.
- Offline speech with installed Windows voices; optional local reference-voice worker requires separate setup and an explicitly provided recording.
- Local chat through the existing llama-cpp adapter when its model is present.
- Ctrl+Alt+Esc cancels queued work, requests cooperative cancellation and pauses listening.

Phase 1 adds validated configuration, a centralized policy boundary, registered tools, task and cancellation metadata, a separate audit database, and AI provider contracts. Tauri and the PyQt fallback share the runtime service.

## Current security limits

The desktop still uses the existing local control mode. **Owner authentication is not configured.** Anyone who can interact with the unlocked Windows session or microphone can issue supported commands. Confirmation is not authentication. The new strict permission policy is a foundation for Phase 2; there is no active owner/guest sign-in flow yet.

Raw keyboard/mouse access can manipulate other applications. This is not a sandbox against malicious code running as your Windows user. Do not use ordinary chat history, notes or settings as a password vault.

The separate security audit stores allowlisted metadata with Windows user/SYSTEM directory permissions. Existing conversation history and notes remain in the original local SQLite database. Audit records are not tamper-proof against the same Windows account.

## Development

Use Python 3.11 on Windows, the packages declared in `Requirements.txt`, Node/npm, Rust's MSVC toolchain and the Tauri Windows build prerequisites. Optional speech-worker requirements are separate in `Requirements.voice.txt`. The existing build uses a Python runtime at `%LOCALAPPDATA%\Jarvis\runtime`.

```powershell
& "$env:LOCALAPPDATA\Jarvis\runtime\Scripts\python.exe" -B -m unittest discover -s scripts/tests -q
& "$env:LOCALAPPDATA\Jarvis\runtime\Scripts\python.exe" -B scripts/smoke_engine.py
```

`python Main.py` starts the PyQt fallback; `python Main.py --check` reports local setup. Tauri uses `Main.py --engine` over JSON lines, with no listening network server.

Model downloads are an explicit setup action and need internet. Browser search opens the configured search website and also needs internet. Core deterministic commands keep working without models or network.

There is no active cloud AI adapter, remote approval, owner authentication, camera/emotion pipeline, autonomous browser agent or image generator in this desktop runtime. The older isolated `Backend/Security` module and its tests are retained, but do not authenticate desktop actions.

[Architecture and limits](docs/architecture.md) Â· [Cleanup record](docs/cleanup-manifest.md) Â· [Build instructions](desktop/README.md)

Verified Phase 1 build: run `Launch-Jarvis-Phase1.cmd`. See [validation report](docs/phase1-validation.md).

The current Phase 1 launcher includes the [voice and search fixes](docs/voice-and-search-fixes.md).
