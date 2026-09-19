# Phase 1 architecture

## Preserved runtime

```text
Tauri/React -> Rust engine bridge -> JSON stdio -> EngineService
PyQt -> Controller adapter ----------------------^
CLI and compatibility adapters -> Services
                                    |
                                 Assistant
                                    |
          parser -> registered tool -> policy -> audit -> existing handler
                                    |                         |
                               task events          desktop / files / local AI
```

The existing deterministic parser and action handlers stay in place. Model output is text, never executable commands. No arbitrary shell or dynamically imported plugin is exposed. The Python stdio transport explicitly sets UTF-8, including in the frozen engine where environment-only encoding settings were insufficient. The Rust bridge and Python request validator reject unknown operations, unexpected fields and renderer-supplied identity/permission claims.

EngineService owns voice, speech, the bounded command queue and background monitoring. Services owns application operations. Controller translates that runtime's events into the original Qt signals.

## Configuration

Backend/Config.py owns validated Settings and schema version 1. Existing flat version-0 files load without a write; the next successful save adds the version. Writes use a temporary file, flush/fsync and atomic replacement before updating memory. Invalid or newer settings are not overwritten and disable automatic microphone activation.

Only real settings are exposed. The addition is audit retention, 1â€“3650 days, default 90. Model paths and existing preferences stay compatible. There are no cloud secrets in the configuration contract.

## Permission and confirmation boundary

Permissions.py defines Risk, Principal, ExecutionContext, Decision and SecurityManager. Every registered action passes the policy before executing. Services routes private memory/index queries, settings, model setup and autostart through a fixed operation-to-risk table.

The existing desktop explicitly creates a legacy_local context for built-in operations from known local sources. This preserves its behavior and is not evidence of owner identity. The UI reports owner authentication as false. High-risk legacy operations retain their existing confirmation flow; a stronger authentication mechanism is not implemented in Phase 1.

Strict contexts allow only declared public low-risk operations without authentication. Other operations require an authenticated principal and exact scope. High-risk strict operations additionally require a non-expired strong_until value. These are in-process policy contracts tested using constructed principals; there is no IPC endpoint that creates authenticated principals, and no working PIN/Windows Hello sign-in.

Confirmation challenges have a request ID, session/principal binding, expiry and one-use consumption. Confirmation re-enters the registered underlying action and rechecks its policy. File confirmations check inode/size/mtime for changes; this is a best-effort stale-target check, not protection against malicious same-user filesystem races.

Raw input, application launch, close, screenshots and system configuration remain conservative high-risk tools. Creating/copying/moving/renaming files are medium-risk, recycling is high-risk. Public help/time/date/stop do not require credentials. Private history access uses the same policy decision.

Rust autostart first obtains a ten-second one-use local request ticket, applies its existing registry change, then reports the result for auditing. The ticket is not owner authentication or a remote approval token. No signing or remote transport is claimed.

## Tools, tasks and cancellation

Tools.py registers the current command families with names, descriptions, risk, input validation, handlers, public/legacy allowances and retry metadata. Validation rejects unknown options, dangerous command names and invalid types/ranges. The existing ActionResult is preserved.

Tasks.py supplies task/step IDs, state, result verification labels and cooperative cancellation/deadline tokens. Task event metadata excludes raw commands and paths. There is no persistent workflow scheduler or model-generated multi-step planner yet. Existing deterministic command batches continue to work.

Engine stop requests bypass the normal request thread pool. Generation checks prevent dequeued work from starting after stop. Cancellation is checked before/after tools, between batch steps, during key input, chunked copy and local generation. Stop does not depend on a successful audit write.

There is no automatic retry of side effects. Pointer position and supported file postconditions can report verified; other successful operations report request_accepted. Native calls, large native moves and OS actions may complete before cancellation is observed. Partial copies can remain, and rollback is not implemented. Deadline tokens stop at checkpoints; they are not a hard real-time timeout.

## Events, persistence and audit

Events.py is a small process-local bus with subscriber failure isolation. Tauri receives task/provider/notification updates; UI activity remains separate from security audit.

Audit.py stores allowlisted identifiers, source, tool, risk, outcome, verification and error class/code. It excludes command text, file targets, arbitrary nested values, model content, passwords and tokens. The Windows directory DACL permits the current process user's SID and SYSTEM, with inheritance protected. It is not encrypted, signed or resistant to tampering by that Windows user or an administrator.

An audit failure before a privileged attempt blocks execution. Failure after an attempted action reports uncertain completion and does not retry. Emergency cancellation remains available without audit storage. Audit retention is applied when the audit store starts; changing retention takes effect on the next startup.

Store.py retains original chat, filename index, notes and simple reminders. This is not the future separated memory system. Existing text history can contain sensitive user-provided content and is not encrypted. Internal Jarvis state paths are excluded from normal file mutation/copy tools; arbitrary OS input remains outside such file-path protection.

## AI and voice

AIProviders.py defines a provider protocol and wraps the installed LocalBrain/llama_cpp implementation. The production orchestrator uses that local adapter only. Online-disabled routing never calls an optional online provider; tests inject a failing provider to verify local fallback. No production online SDK, key setting, service or adapter is installed.

Whisper, Windows SAPI and the existing optional reference-voice worker remain unchanged in their roles. Models load lazily and use existing CPU settings. Missing model/audio devices yield a limitation/error instead of invented success. Speaker identity is distinct from synthesis and is not implemented by this phase.

## Later phases

Phase 2 must provide actual owner enrollment, Windows-appropriate credential protection, rate-limited strong authentication, guest state, expiry and identity-aware memory before strict policy replaces legacy behavior. Voice alone must never authorize high-risk actions.

Later phases can add voice profile consent/identity interfaces, memory controls, recurring tasks/briefings, real verified local/optional online adapters, a validated planner, browser tools and optional vision. Remote approval needs a verified authenticated transport, signing/key storage, request-specific scopes, expiry, replay protection, rejection/cancellation and audit. No remote listener is introduced now.

These future capabilities are neither installed nor represented as working settings in Phase 1.
