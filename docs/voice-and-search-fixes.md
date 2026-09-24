# Voice and search fixes — 16 September 2026

These changes address failures observed in the running application without replacing its speech library, command engine, model files or saved preferences.

## Changes

- Automatic recognition now selects between the English and Urdu options shown in Settings. Ambiguous language results request a repeat or fixed language instead of becoming unrelated-language commands.
- Audio entirely rejected by the recognizer's voice activity detector is discarded before decoding segment text.
- Common Windows application names are included in the existing recognizer's prompt. A Windows-generated “Jarvis, open Notepad” recording initially decoded as “nodepad”; the same recording decoded correctly after this change.
- Unclear speech displays a retry message.
- Pausing during model loading no longer starts microphone capture afterward. A transcription from an earlier listening session is discarded if listening was restarted or its settings changed.
- Google/YouTube search prefixes accept spoken sentence pauses, including “Search Google. Who is Elon Musk.”
- A provider-only request such as “Search on YouTube” opens that site. An immediately following search in the same command batch keeps the requested provider.
- Explicit providers override inherited ones. Context does not survive another kind of action or another request. Dictation and query punctuation remain literal.

Files changed: `Backend/VoiceInput.py`, `Backend/Commands.py`, two new regression-test files, `scripts/check_voice_fixture.py`, this report and the Phase 1 launcher. No dependency or frontend/native source change is required for these fixes.

## Validation

- Full Python suite: **125 tests passed**, including the original baseline.
- Real local model: synthetic Windows voice -> Whisper -> wake-word gate -> expected Notepad action; actual silence rejected.
- The synthetic audio was written to a local WAV. No microphone recording was taken for this test, and no desktop action was executed from it.
- The user's observed search phrases were exercised through the real Assistant with a mocked desktop adapter; the correct Google and YouTube providers were passed to it.
- Source engine multilingual JSON startup/command/emergency/exit smoke check passed.
- The rebuilt packaged engine passed the same smoke check. Verified build: `artifacts/staging/Jarvis-20260916-161017`; its source/binary hashes and validation results are in `build-manifest.json`.

Repeat the model check with the locally generated fixture:

```powershell
& "$env:LOCALAPPDATA\Jarvis\runtime\Scripts\python.exe" -X utf8 -B scripts/check_voice_fixture.py artifacts/voice-validation/windows-voice-open-notepad.wav --expect-action open --expect-target notepad
```

## Limits

A clean synthetic English sentence does not establish recognition accuracy for the user's microphone, accent, environment or Urdu speech. The exact intended failing voice command and preferred language have not been provided. The new language thresholds are conservative heuristics; unclear speech can require repeating the command or selecting English/Urdu explicitly.

Browser actions still open a site or search-results page. They do not autonomously read pages, click results or guarantee video playback. Offline voice/command parsing does not make web searches work without internet.

The original packaged release and previous verified Phase 1 build remain available. Owner authentication remains unconfigured as documented for Phase 1.

Final native UI check: the rebuilt application was visible, connected to its local engine, and displaying an active microphone. `Launch-Jarvis-Phase1.cmd` points to this verified build. Live speech accuracy still needs the user’s command test.
