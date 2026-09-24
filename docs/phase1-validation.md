# Phase 1 validation â€” 15 September 2026

Verified build: `artifacts/staging/Jarvis-20260915-232156`.
Launch it with `Launch-Jarvis-Phase1.cmd`. The original `Launch-Jarvis.cmd` and `artifacts/Jarvis` remain available.

## Checks actually run

| Check | Result |
| --- | --- |
| Python unittest discovery in scripts/tests | 111 passed, including the original 74 |
| Frontend Vitest bridge suite | 4 passed |
| TypeScript and Vite production build | Passed |
| Tauri Windows release build, --no-bundle | Passed |
| PyInstaller engine packaging | Passed |
| Real source-engine stdio smoke | Passed |
| Real packaged-engine stdio smoke | Passed |
| Multilingual input/output under forced cp1252 environment | Passed after explicit UTF-8 transport fix |
| Native app with existing local profile | Visible window; local engine connected; multilingual history displayed |
| Ctrl+Alt+J | UI entered microphone-active state and began loading local speech recognition |
| Ctrl+Alt+Esc | UI returned to microphone-paused state and reported stop requested |
| PyQt fallback construction/settings helper in temporary profile | Passed |
| Chat compatibility input containing an application command | Stayed conversation; mocked application launcher was not called |
| Original desktop and engine hashes against Phase 0 checkpoint | Both unchanged |
| Whitespace check limited to changed tracked Phase 1 files | Passed |

The engine smoke uses a temporary profile, disabled audio, no search roots, a local time command, emergency stop and clean shutdown. It also round-trips Unicode settings and requires UTF-8 JSON despite a legacy code-page environment.

The first native UI check exposed a real frozen-Python encoding failure with existing multilingual history. The smoke check reproduced it, EngineService explicitly configured UTF-8 streams, the tests were rerun, and a corrected engine was repackaged and verified in the native app.

New Python coverage includes schema migration/write failures, policy denial/expiry/scopes, session-bound confirmation, metadata-only audit and storage failure, provider fallback, input validation, batch/queue cancellation, deadlines, IPC field rejection and emergency handling with a saturated normal request pool. Authentication tests exercise constructed policy facts, not a real owner login.

## Limits

- Live speech transcription accuracy, speaker identity and real local-model answers were not validated by these smoke checks.
- Physical file/keyboard/mouse side effects mostly remain covered by the existing unit tests using mocks/temporary files. The two global shortcuts were exercised in the actual app.
- Owner enrollment, stronger authentication, real guest sessions, memory isolation, recurring scheduling, remote approval, browser autonomy and vision remain future phases.
- The isolated legacy camera tests ran; no webcam/owner-recognition feature was enabled.
- No real online AI adapter or remote approval service was called or added.
- PyInstaller reported an optional missing tzdata hook and dependency deprecation notices; the packaged smoke still passed. Future timezone scheduling needs its own verified data strategy.
- Repository-wide git diff --check reports a pre-existing trailing blank line in Backend/LanguageManager.py, outside these Phase 1 edits.
- The new build was left open with its microphone paused after the emergency-stop test.

Audit ACLs limit other Windows accounts but are not tamper-proof against the current account. Local desktop mode still relies on the unlocked Windows session and confirmation, not owner authentication.

See [architecture](architecture.md) for the exact security, cancellation and verification limits.

Cleanup limitation: Windows denied removal of DLLs in the superseded staging build. Remaining generated files are listed in the cleanup record; no security settings were changed to force removal.
