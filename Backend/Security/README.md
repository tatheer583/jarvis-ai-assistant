# Jarvis Personal Security (CV Foundation)

Local webcam presence + owner-vs-unknown verification + explicit state machine.

**No Windows lock in this phase. No cloud biometrics. Frames are never written to disk.**

## States

`STARTING` → `NO_PERSON` / `UNKNOWN_PERSON` / `AUTHORIZED` → `PROTECTION_PENDING` → `PROTECTED`  
`CAMERA_ERROR` on camera failure (Jarvis keeps running).

Legacy aliases: `ABSENT`=`NO_PERSON`, `PROTECTING`=`PROTECTED`, `ERROR`=`CAMERA_ERROR`.

## Config (`.env`)

- `SecurityEnabled` / `CameraEnabled`
- `SecurityEnforce=false` (default): observe + greet; commands not gated
- `OwnerName=Tatheer`
- `AbsenceTimeout`, `ProtectThresholdSec`, `PresenceCheckInterval`
- Emergency disable: create `Data/Security/DISABLE`

## Owner enrollment

Use `Backend.Security.enrollment` helpers when ready. Without a local template, presence-only AUTHORIZED fallback applies unless `RequireFaceEnrollment=true`.

## Public API

- `SecurityManager` / `PresenceService`
- `is_command_allowed()` / `allows_commands()`
- `consume_owner_recognized_event()`
