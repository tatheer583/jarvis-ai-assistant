# Response speed and Mission control

## Changes

Local chat now streams visible text to the desktop and queues the first sentence for Windows speech while generation continues. Ordinary replies use up to two sentences and a 160-token allowance; explicit detailed requests/drafts retain 384 tokens. Both remain limited local-model answers.

The existing faster-whisper 1.2.1 Silero V6 model is reused as a streaming speech detector. Its ONNX input schema is checked at startup; if it cannot be used, the microphone falls back to the previous WebRTC detector. No new package or model download was required. The 14-second maximum utterance length and wake-word/confirmation checks remain.

Mission control shows real engine state, reminders due by tonight, current-session task outcomes, CPU/memory use, and per-command response timing. It reports unconfigured owner authentication honestly. The existing microphone pause threshold is now editable in Settings.

## Measured results

Hardware: approximately 7.85 GB usable RAM, four physical/eight logical CPUs, no GPU assumption. Background load and available RAM varied considerably. These are single-run synthetic/local checks, not controlled end-to-end microphone or accuracy benchmarks.

| Measurement | Result |
| --- | --- |
| Original warm model: full buffered answer | 9.30 s |
| Original warm model: first sentence already available internally | 1.98 s |
| Updated warm model: first visible text | 0.41 s |
| Updated warm model: first sentence available for speech queue | 6.92 s |
| Updated warm model: complete two-sentence answer | 12.36 s |
| Updated cold request, including loading: first visible text | 32.84 s |
| Updated cold request: complete answer | 49.57 s |

The improvement established by the updated run is first text arriving before its own full answer (0.41 vs 12.36 seconds). Total generation did **not** improve consistently across separate runs. Do not market these numbers as a controlled overall speedup. Cold model loading, speech recognition, Windows audio startup and other applications can still add delay.

The steady 220 Hz tone fixture reproduced a false utterance at 14.01 seconds in the original WebRTC path. The neural path produced no utterance for that tone or the tested random noise. For the synthetic spoken “Jarvis. Open Notepad.” fixture, both detectors retained the command; endpoint times were 2.79 seconds (WebRTC) and 2.85 seconds (neural), so clean-speech endpointing was not faster at the unchanged 850 ms setting. The neural path avoids the measured false-noise utterance, rather than shortening genuine dictation.

Actual local recognition of the neural-segmented recording produced the open action targeting Notepad, with no desktop action executed. This does not establish live accent/Urdu/microphone accuracy.

## Verification before packaging

- Existing baseline: 125 Python tests passed before changes.
- Updated suite: 142 Python tests passed.
- Frontend: 9 tests passed.
- Frontend production build: passed.
- Source benchmarks: real installed local model and synthetic speech fixture completed.
- A pre-existing camera-service test had a real 10 ms timeout race. Its clock is now controlled, and it tests both sides of the expiry boundary.
- Packaged/native checks are recorded below only after they run.

## Reproduce

Use the installed Jarvis Python runtime to run:

    python -B -m unittest discover -s scripts/tests -q
    python scripts/benchmark_response.py --mode chat --output artifacts/performance-validation/chat-repeat.json
    python scripts/benchmark_response.py --mode voice --output artifacts/performance-validation/voice-repeat.json
    python scripts/smoke_engine.py --executable dist/jarvis-engine/jarvis-engine.exe
    python scripts/smoke_streaming.py --executable dist/jarvis-engine/jarvis-engine.exe --output artifacts/performance-validation/packaged-streaming.json

Stop other Jarvis model processes before inference benchmarks on this laptop. Microphone timing measurements do not include actual user speech or physical speaker playback.

## Scope limits

Owner authentication, restricted guest sessions, protected credentials, remote approval, camera identity, emotion inference and autonomous planning are not implemented by this performance/UI update. Existing confirmations and Ctrl+Alt+Esc remain essential. Research and next decisions are in [open-source-research.md](open-source-research.md).

## Packaged verification: deployment blocked

The PyInstaller build completed. The isolated packaged startup, UTF-8 IPC, time command, offline state, emergency request and clean shutdown smoke passed outside the restricted tool environment.

The additional **real packaged chat test failed**. Windows returned error 4551 when loading ggml-cpu.dll / ggml.dll. The Windows Code Integrity Operational log recorded event IDs 3033 and 3077, identifying an Enterprise signing-policy rejection. The packaged llama.dll consequently could not resolve its dependency. SHA-256 checks show the new copies match both the existing Python runtime and previous staged release DLLs.

No App Control policy, signing requirement, file trust flag, antivirus setting or Windows protection was changed. The model-speed measurements above are from the existing Python runtime, and do not establish successful portable chat. The normal launchers must not be promoted on the basis of the passing basic smoke alone. An approved/signed native runtime is required before portable chat can be released as verified.

## Final build status

- Frontend source, nine tests and production assets are complete. A browser-only copy is saved at artifacts/mission-control-preview. Browser preview cannot control the computer.
- Tauri native compilation **failed**: Windows App Control rejected the Cargo build-script-build executable with OS error 4551. No new native desktop release was produced or promoted.
- A later isolated source-engine chat check also failed because Windows rejected the installed runtime's llama.dll, including when the check was retried outside the restricted tool environment. Earlier in-process benchmarks succeeded; they are historical measurements, not proof that the current policy permits the full engine.
- The previous release was reopened (PID 17040 at verification time). Launch-Jarvis.cmd and Launch-Jarvis-Phase1.cmd were not changed.
- Browser visual QA could not run: the Browser tool failed to initialize its kernel assets. React DOM interaction tests passed, but no new-dashboard screenshot is claimed.
- Remaining deployment dependency: an approved signing/trust path for the specific AI DLLs and native build helper. No policy bypass or protection change was attempted.

Machine-readable results are in artifacts/performance-validation/final-validation.json. The original executable hashes were checked again against the Phase 0 record.
