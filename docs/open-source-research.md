# Jarvis: open-source research and implementation decisions

Reviewed 2026-09-16. This is an evolution of the existing Windows Tauri/React/Python app. The desktop engine, local models, confirmation flow and emergency shortcut remain in place.

## Verified sources

| Project | What its own documentation establishes | Decision for this app |
| --- | --- | --- |
| [OpenVoiceOS core](https://github.com/OpenVoiceOS/ovos-core) | A voice assistant core with explicitly installed skills. | Keep the existing tool registry and service boundaries. Do not replace the working Windows engine with another platform. |
| [OHF Wyoming](https://github.com/OHF-Voice/wyoming) | Typed events for speech stages, including streaming text/audio. The protocol explicitly has no authentication or encryption and is intended for trusted networks. | Apply the staged, streaming interaction pattern to existing local stdio IPC. Do not add a public listener or use Wyoming for remote owner approval. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | CPU/int8 transcription and integrated Silero speech detection. | Retain the installed version 1.2.1 and Whisper base. Reuse its bundled V6 ONNX detector before transcription, with a verified schema and WebRTC fallback. |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | CPU/Windows support and example streaming recognition, requiring a different native implementation and model format. | A future measured alternative, not an automatic replacement. Its project benchmarks do not establish speed on this laptop. |
| [openWakeWord](https://github.com/dscripka/openWakeWord) | Dedicated wake-word detection; Windows uses ONNX. Its code is Apache-2.0, while included pretrained models have a separate noncommercial license. | Candidate for reducing unnecessary Whisper work later. It is not installed or represented as working here; model suitability, licensing and English/Urdu behavior require a separate evaluation. |

No repository installer, downloaded script, additional AI model, cloud SDK or remote service was installed during this work. References informed design decisions; third-party source was not copied into the app.

## Implemented in this update

- Incremental local chat text reaches the desktop while generation continues.
- Windows speech starts at the first complete sentence. The remaining reply is queued once, with cancellation applied to all queued audio.
- Everyday replies stop after two complete sentences; explicit detailed requests and drafts retain a longer generation allowance.
- The microphone uses the already-bundled neural speech detector to reject background signals before waiting for a full utterance.
- Existing configurable end-of-speech timing is exposed in Settings. Custom timings are preserved.
- Mission control displays actual engine, microphone, CPU/memory, reminders, session tasks and response measurements. It does not manufacture identity, verification or online-service status.
- A deterministic clock replaces a real 10 ms timing dependency in an existing security-service test.

## Why these changes come first

Local measurements showed usable model output arriving well before the full answer. Streaming improves the time to visible/spoken output without changing the model or adding a service. A synthetic steady tone reproduced a 14-second false utterance in the old detector, while the bundled neural detector rejected it. These are measured, bounded improvements; they do not establish accuracy for every accent, room or microphone.

The laptop has about 7.8 GB usable RAM. Loading multiple chat/speech stacks together would add pressure. Keep one local chat model, lazy model initialization, bounded queues and a small desktop UI. Further tuning should use the committed benchmark script and compare equivalent input, cold/warm state and background load.

## Remaining work

The current desktop still reports legacy local control and unconfigured owner authentication. Voice is not strong authentication. PIN/Windows-backed owner authentication, guest sessions, protected credentials and authorization expiry belong to the next security implementation. Camera identity, expression inference, remote approval, arbitrary browser automation and autonomous multi-step planning are not delivered by this update.

A movie-style general intelligence is not a verified capability of this app. The practical target is a responsive local assistant with clear feedback, useful tools, measured performance and explicit permission boundaries.
