# Phase 1 cleanup

A source checkpoint was created at `artifacts/phase0-baseline/source.zip` with SHA-256 metadata before changes. The checkpoint recorded 13 unreadable legacy graphics as untouched; it does not pretend to contain them.

## Removed

- `gen_out.txt`: empty generated output.
- `debug_groq.py`: redundant standalone diagnostic; supported checks remain `Main.py --check` and the existing diagnostics.
- Obsolete root README cloud-key setup and claims of active remote/image/browser-agent functionality were replaced with accurate local runtime documentation.

The Phase 1 staged application omits the redundant external frontend copy because Tauri embeds the built UI. The preserved working release folder was not pruned.

## Retained deliberately

- `Data/`, chat history, browser profiles, notes and user files.
- Existing models and Python runtime; optional voice-worker packages are not removed from the user's environment.
- `.env`: never read for values or erased in this cleanup; the isolated legacy security configuration still has dotenv support.
- `Backend/Security/`, its enrollment script and tests: isolated legacy subsystem; not wired to desktop authorization.
- BrowserAutomation, LanguageManager, StatusIO and compatibility modules: retained until their individual consumers can be retired with verified replacements.
- Existing launchers, graphics, `artifacts/Jarvis` and original executables.
- Build/package lockfiles and reproducibility scripts.

No broad folder deletion, dependency purge or removal of user-owned data was performed. Cloud services are not mandatory in the active desktop runtime. This cleanup is intentionally limited to proven redundant material.

Removal of superseded generated staging directory `artifacts/staging/Jarvis-20260915-231440` was attempted after the corrected build passed and no matching app process remained. Windows denied deletion of a packaged `.pyd` DLL both inside and outside the sandbox, so remaining files were retained without changing OS protections or file ownership. The verified build is `Jarvis-20260915-232156`.
