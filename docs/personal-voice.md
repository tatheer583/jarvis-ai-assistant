# Personal voice: implementation and verification

## Audit and choice

The existing SAPI output and optional Pocket TTS subprocess remain the integration point. Previously, each personal reply loaded a new model; Settings forced Windows speech on save; personal failures had no fallback. Owner enrollment recordings were also used as TTS references without distinct synthesis consent.

| Approach | CPU / Windows / offline | Personal voice | Resource and setup tradeoff |
| --- | --- | --- | --- |
| Windows SAPI | Native Windows, CPU, offline | Installed system voices only | Lowest setup cost; preserved fallback |
| Pocket TTS | CPU-oriented Python; Windows PyTorch; cached weights offline | Reference WAV supported by cloning-enabled weights | About 100M parameters; two CPU threads. Upstream timing is on newer hardware, not this i5. Exact RAM must be measured. Existing optional dependency, selected for bounded testing. |
| Piper | Local CPU speech; additional platform packaging | Custom trained voice, not immediate WAV prompting | Requires dataset/training workflow for a personal voice |
| F5-TTS | Python, local inference; accelerator-oriented setup examples | Audio reference plus transcript | More involved inference dependencies; no verified speed/RAM result for this laptop; not installed |

Primary references: [Pocket TTS](https://github.com/kyutai-labs/pocket-tts), [Piper training](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/TRAINING.md), [F5-TTS](https://github.com/SWivid/F5-TTS).

## Implemented boundaries

- `VoiceOutput` exposes speak/stop/is_speaking/set_voice/set_speed/set_volume. Existing say/append callers remain compatible.
- SAPI remains available. Personal speech uses a separate CPU worker with a cached model/reference and streaming audio output. The worker unloads after 60 idle seconds and is terminated, including Windows child processes, on Stop.
- Personal workers refuse startup below 1.5 GiB available memory; their process tree has a monitored 2.25 GiB working-set threshold and a 90-second request timeout. These are operational guards, not guarantees of memory availability or model requirements.
- Personal speed changes playback rate and pitch; volume scales audio. Model prosody controls are not claimed.
- Runtime worker network connections are disabled, including direct HTTP downloads. Missing weights fail and system speech takes over. Explicit setup downloads public model files only.
- The UI has no functioning online provider. Its online option is disabled.
- Record/import requires consent. Eight-second microphone recording is cancellable and pauses STT. Import supports 3–30 second 16-bit PCM WAV. Private reference copies live under `%LOCALAPPDATA%/Jarvis/voice/recordings`; model cache under `voice/model`; local state directory `voice/config` is reserved. Recordings receive the existing Windows directory ACL protection.
- Delete removes only Jarvis's managed personal recording and consent; it does not delete the original imported WAV, owner identity samples, or public model weights.
- Startup speaks the configured owner/assistant names via the selected engine. It does not claim identity was authenticated or all models are ready.
- Packaged builds include the worker script but require the separately installed optional Python TTS runtime. No updated native executable was built in this task.

## Hardware findings

Observed approximately 7.85 GiB total RAM and 1.1–1.34 GiB available during this work. Installed optional packages: pocket-tts 3.1.0 and torch 2.14.0. A 90-second bounded offline probe imported Pocket TTS, then stopped at its 1.5 GiB free-memory guard after 37.81 seconds (355.4 MB peak process-tree working set, 30.36 CPU-seconds). Model load, synthesis, and playback were not reached. These numbers are not the model's full RAM requirements. No personal voice recording was captured or uploaded.

The complete regression run after this work passed 158 Python tests with 31 subtests, and the frontend passed 10 tests plus its production build. The real engine IPC smoke test also passed. A separate earlier run exposed a Windows Application Control rejection for an unchanged PyAV speech-detector DLL; the final regression run did not reproduce that failure, but the policy restriction remains an environment risk.

Separately, Windows Application Control rejected a PyAV DLL used by the unchanged speech detector. Do not disable policy as a workaround. The failure requires administrator-approved environment repair. More free RAM (or a RAM upgrade) may help model testing, but it will not resolve policy blocks.

## Commands (from the recovered repository)

```powershell
& "$env:LOCALAPPDATA\Jarvis\runtime\Scripts\python.exe" -B -m pytest scripts/tests -q
& "$env:LOCALAPPDATA\Jarvis\runtime\Scripts\python.exe" scripts/check_personal_voice.py --load-model --timeout 90
```

Only after imports/model loading succeed, use `--play` for a short built-in-voice playback test. A personal test additionally needs `--reference` pointing to your own WAV and `--consent`. A built-in voice test does not establish that your personal voice is working. Model weights can be prepared explicitly with `scripts/download_models.py --voice`; access restrictions on cloning-capable weights must be satisfied legitimately.
