"""SecurityManager / PresenceService — local CV presence + owner verification."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from Backend.Security.camera import CameraError, CameraWorker
from Backend.Security.config import SecurityConfig, load_security_config
from Backend.Security.face_verifier import FaceVerifier, IdentityResult
from Backend.Security.gate import is_sensitive_command
from Backend.Security.log import log_security_event
from Backend.Security.presence import PresenceDetector
from Backend.Security.state_machine import InvalidTransition, SecurityStateMachine
from Backend.Security.states import SecurityState

log = logging.getLogger("Jarvis.Security.Service")

SpeakFn = Callable[[str], None]
StatusFn = Callable[[str], None]

_GREET_FROM = frozenset({
    SecurityState.NO_PERSON,
    SecurityState.UNKNOWN_PERSON,
    SecurityState.PROTECTION_PENDING,
    SecurityState.PROTECTED,
    SecurityState.WARNING,
    SecurityState.STARTING,
})

_RESTRICTED_STATES = frozenset({
    SecurityState.UNKNOWN_PERSON,
    SecurityState.PROTECTION_PENDING,
    SecurityState.PROTECTED,
    SecurityState.WARNING,
    SecurityState.LOCKED,
    SecurityState.NO_PERSON,
    SecurityState.CAMERA_ERROR,
})


class PresenceService:
    """Background presence + local face verification monitor.

    - Distinguishes AUTHORIZED (owner) vs UNKNOWN_PERSON using local templates.
    - If no template is enrolled, falls back to presence-only AUTHORIZED
      (unless RequireFaceEnrollment=true).
    - Does NOT lock Windows.
    - Greeting / unauthorized announcements fire once per transition (with cooldown).
    - ``allows_commands()`` / ``is_command_allowed()`` respect ``enforce`` (default False).
    """

    def __init__(
        self,
        config: SecurityConfig | None = None,
        *,
        on_speak: SpeakFn | None = None,
        on_status: StatusFn | None = None,
        verifier: FaceVerifier | None = None,
        camera: CameraWorker | None = None,
    ) -> None:
        self.config = config or load_security_config()
        self._on_speak = on_speak
        self._on_status = on_status
        self._machine = SecurityStateMachine(SecurityState.STARTING)
        self._camera = camera or CameraWorker(self.config.camera_index)
        self._detector = PresenceDetector(
            motion_threshold=self.config.motion_threshold,
            min_contour_area=self.config.min_contour_area,
        )
        self._verifier = verifier or FaceVerifier(
            self.config.owner_template_path,
            match_threshold=self.config.face_match_threshold,
            require_enrollment=self.config.require_face_enrollment,
            min_face_size=self.config.face_min_size,
            min_brightness=self.config.face_min_brightness,
            max_brightness=self.config.face_max_brightness,
            min_laplacian_var=self.config.face_min_laplacian_var,
        )
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._person_streak = 0
        self._absent_streak = 0
        self._owner_streak = 0
        self._unknown_streak = 0
        self._absent_since: float | None = None
        self._pending_since: float | None = None
        self._warmup_left = self.config.warmup_frames
        self._activity_event = threading.Event()
        self._started = False
        self._last_greeting_mono: float | None = None
        self._last_unauthorized_mono: float | None = None
        self._owner_recognized_event = threading.Event()

    def start(self) -> bool:
        with self._lock:
            if self._started:
                return True
            if not self.config.effective_enabled():
                log.info("Security presence disabled (config or DISABLE flag)")
                log_security_event(
                    self.config.log_path,
                    event="disabled",
                    reason="SecurityEnabled=false or DISABLE flag",
                )
                return False
            if not self.config.camera_enabled:
                log.info("Security camera disabled via CameraEnabled=false")
                log_security_event(
                    self.config.log_path,
                    event="camera_disabled",
                    reason="CameraEnabled=false",
                )
                return False

            self._stop.clear()
            self._warmup_left = self.config.warmup_frames
            self._detector.reset()
            self._verifier.reload_templates()
            try:
                self._camera.open()
            except CameraError as exc:
                log.error("Camera open failed: %s", exc)
                self._safe_transition(SecurityState.CAMERA_ERROR, f"camera_open_failed:{exc}")
                log_security_event(
                    self.config.log_path,
                    event="camera_error",
                    state_to=SecurityState.CAMERA_ERROR.value,
                    reason=str(exc),
                )
                return False

            log_security_event(
                self.config.log_path,
                event="camera_available",
                reason=f"index={self.config.camera_index}",
            )
            self._thread = threading.Thread(
                target=self._run_loop,
                name="JarvisSecurityService",
                daemon=True,
            )
            self._thread.start()
            self._started = True
            log_security_event(
                self.config.log_path,
                event="security_started",
                state_to=self._machine.state.value,
                reason="cv_foundation",
                enrolled=self._verifier.is_enrolled,
            )
            return True

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        self._camera.close()
        with self._lock:
            self._started = False
            self._thread = None
        log_security_event(
            self.config.log_path,
            event="service_stopped",
            state_from=self.get_state().value,
            reason="stop",
        )

    def get_state(self) -> SecurityState:
        with self._lock:
            return self._machine.state

    def is_enrolled(self) -> bool:
        return self._verifier.is_enrolled

    def allows_commands(self) -> bool:
        return self.is_command_allowed(None)

    def is_command_allowed(self, command: str | None = None) -> bool:
        if not self.config.effective_enabled():
            return True
        if not self.config.enforce:
            return True
        # Fail closed for sensitive actions until owner is enrolled when required.
        if self.config.require_face_enrollment and not self.is_enrolled():
            if command is None or is_sensitive_command(command):
                return False
        state = self.get_state()
        if state in {SecurityState.AUTHORIZED, SecurityState.STARTING}:
            return True
        if state in _RESTRICTED_STATES:
            if command is None:
                return False
            return not is_sensitive_command(command)
        return True

    def notify_user_activity(self) -> None:
        self._activity_event.set()

    def is_running(self) -> bool:
        return self._started and not self._stop.is_set()

    def consume_owner_recognized_event(self) -> bool:
        """True once per owner recognition transition (for optional TTS wiring)."""
        if self._owner_recognized_event.is_set():
            self._owner_recognized_event.clear()
            return True
        return False

    def _emit_speak(self, text: str) -> None:
        if not text or not self._on_speak:
            return
        try:
            self._on_speak(text)
        except Exception as exc:
            log.debug("on_speak failed: %s", exc)

    def _maybe_announce(self, previous: SecurityState, current: SecurityState) -> None:
        now = time.monotonic()
        if current == SecurityState.AUTHORIZED and previous in _GREET_FROM:
            cooldown = self.config.greeting_cooldown_sec
            if self._last_greeting_mono is None or (now - self._last_greeting_mono) >= cooldown:
                self._last_greeting_mono = now
                self._owner_recognized_event.set()
                log_security_event(
                    self.config.log_path,
                    event="owner_detected",
                    state_from=previous.value,
                    state_to=current.value,
                    reason="authorized_transition",
                )
                self._emit_speak(self.config.authorized_greeting)
        elif current == SecurityState.UNKNOWN_PERSON and previous != SecurityState.UNKNOWN_PERSON:
            cooldown = self.config.warning_cooldown_sec
            if (
                self._last_unauthorized_mono is None
                or (now - self._last_unauthorized_mono) >= cooldown
            ):
                self._last_unauthorized_mono = now
                log_security_event(
                    self.config.log_path,
                    event="unknown_person_detected",
                    state_from=previous.value,
                    state_to=current.value,
                    reason="unknown_transition",
                )
                self._emit_speak(self.config.unauthorized_message)

    def _safe_transition(self, target: SecurityState, reason: str) -> None:
        with self._lock:
            previous = self._machine.state
            try:
                result = self._machine.transition(target, reason)
            except InvalidTransition as exc:
                log.warning("Rejected transition: %s", exc)
                log_security_event(
                    self.config.log_path,
                    event="invalid_transition",
                    state_from=previous.value,
                    state_to=target.value,
                    reason=str(exc),
                )
                return
            if not result.changed:
                return

            event = "state_change"
            if result.current == SecurityState.NO_PERSON and result.previous == SecurityState.AUTHORIZED:
                event = "owner_left"
            elif result.current == SecurityState.PROTECTION_PENDING:
                event = "protection_pending"
                self._pending_since = time.monotonic()
            elif result.current == SecurityState.PROTECTED:
                event = "protected"
            elif result.current == SecurityState.CAMERA_ERROR:
                event = "camera_error"

            if result.current != SecurityState.PROTECTION_PENDING:
                # Keep pending timer only while sitting in PROTECTION_PENDING.
                if result.previous == SecurityState.PROTECTION_PENDING:
                    self._pending_since = None

            log_security_event(
                self.config.log_path,
                event=event,
                state_from=result.previous.value,
                state_to=result.current.value,
                reason=reason,
            )
            self._maybe_announce(result.previous, result.current)
            if self._on_status:
                try:
                    self._on_status(f"Security: {result.current.value}")
                except Exception:
                    pass

    def _run_loop(self) -> None:
        log.info("Presence/face loop started (enrolled=%s)", self._verifier.is_enrolled)
        while not self._stop.is_set():
            try:
                self._tick()
            except CameraError as exc:
                log.error("Camera error in loop: %s", exc)
                self._safe_transition(SecurityState.CAMERA_ERROR, f"camera_error:{exc}")
                self._camera.close()
                time.sleep(2.0)
                try:
                    self._camera.open()
                    self._detector.reset()
                    self._warmup_left = self.config.warmup_frames
                    log_security_event(
                        self.config.log_path,
                        event="camera_available",
                        reason="reopen",
                    )
                    self._safe_transition(SecurityState.STARTING, "camera_reopen")
                except CameraError:
                    time.sleep(3.0)
            except Exception as exc:
                log.exception("Unexpected presence loop error: %s", exc)
                self._safe_transition(
                    SecurityState.CAMERA_ERROR, f"loop_error:{type(exc).__name__}"
                )
                time.sleep(1.0)
            self._stop.wait(self.config.frame_interval_sec)
        log.info("Presence/face loop exiting")

    def _classify_present_frame(self, frame) -> IdentityResult:
        result = self._verifier.verify_owner(frame)
        if result.identity == IdentityResult.ERROR:
            # Fail soft for loop stability; do not invent OWNER.
            return IdentityResult.NO_FACE
        if result.identity == IdentityResult.NO_TEMPLATE:
            if self.config.require_face_enrollment:
                return IdentityResult.UNKNOWN
            # Documented fallback: presence-only AUTHORIZED path until enrollment.
            return IdentityResult.OWNER
        return result.identity

    def _update_identity_streaks(self, identity: IdentityResult) -> None:
        if identity == IdentityResult.OWNER:
            self._owner_streak += 1
            self._unknown_streak = 0
        elif identity == IdentityResult.UNKNOWN:
            self._unknown_streak += 1
            self._owner_streak = 0
        else:
            self._owner_streak = max(0, self._owner_streak - 1)
            self._unknown_streak = max(0, self._unknown_streak - 1)

    def _stable_owner(self) -> bool:
        return self._owner_streak >= self.config.face_stable_frames

    def _stable_unknown(self) -> bool:
        return self._unknown_streak >= self.config.face_stable_frames

    def _presence_target_state(self) -> SecurityState | None:
        if self._stable_owner():
            return SecurityState.AUTHORIZED
        if self._stable_unknown():
            return SecurityState.UNKNOWN_PERSON
        return None

    def _tick(self) -> None:
        frame = self._camera.read()
        if frame is None:
            raise CameraError("empty_frame")

        present = bool(self._detector.person_present(frame))
        identity = IdentityResult.NO_FACE
        if present:
            identity = self._classify_present_frame(frame)
        del frame

        if self._warmup_left > 0:
            self._warmup_left -= 1
            return

        if present:
            self._person_streak += 1
            self._absent_streak = 0
            self._update_identity_streaks(identity)
        else:
            self._absent_streak += 1
            self._person_streak = 0
            self._owner_streak = 0
            self._unknown_streak = 0

        stable_present = self._person_streak >= self.config.presence_stable_frames
        stable_absent = self._absent_streak >= self.config.absence_stable_frames
        state = self.get_state()
        now = time.monotonic()
        target = self._presence_target_state() if stable_present else None

        if self._activity_event.is_set():
            self._activity_event.clear()
            if state in {SecurityState.PROTECTION_PENDING, SecurityState.NO_PERSON, SecurityState.PROTECTED}:
                if target == SecurityState.UNKNOWN_PERSON or (
                    stable_present and not self._stable_owner()
                ):
                    dest = (
                        SecurityState.UNKNOWN_PERSON
                        if state == SecurityState.PROTECTED
                        else SecurityState.WARNING
                    )
                    self._safe_transition(dest, "activity_unknown_or_unverified")
                elif target == SecurityState.AUTHORIZED:
                    self._absent_since = None
                    self._pending_since = None
                    self._safe_transition(SecurityState.AUTHORIZED, "activity_owner_return")

        if state == SecurityState.STARTING:
            if target is not None:
                self._absent_since = None
                self._safe_transition(target, f"startup_{target.value.lower()}")
            elif stable_absent:
                self._absent_since = now
                self._safe_transition(SecurityState.NO_PERSON, "stable_absence")
            return

        if state == SecurityState.AUTHORIZED:
            if stable_absent:
                self._absent_since = now
                self._safe_transition(SecurityState.NO_PERSON, "owner_left")
            elif target == SecurityState.UNKNOWN_PERSON:
                self._safe_transition(SecurityState.UNKNOWN_PERSON, "face_mismatch")
            return

        if state == SecurityState.UNKNOWN_PERSON:
            if stable_absent:
                self._absent_since = now
                self._safe_transition(SecurityState.NO_PERSON, "unknown_left")
            elif target == SecurityState.AUTHORIZED:
                self._absent_since = None
                self._safe_transition(SecurityState.AUTHORIZED, "owner_recognized")
            return

        if state == SecurityState.NO_PERSON:
            if target is not None:
                self._absent_since = None
                self._safe_transition(target, f"return_{target.value.lower()}")
                return
            if self._absent_since is None:
                self._absent_since = now
            elif (now - self._absent_since) >= self.config.absence_timeout_sec:
                self._safe_transition(
                    SecurityState.PROTECTION_PENDING,
                    f"absence_timeout_{self.config.absence_timeout_sec}s",
                )
            return

        if state == SecurityState.PROTECTION_PENDING:
            if target == SecurityState.AUTHORIZED:
                self._absent_since = None
                self._pending_since = None
                self._safe_transition(SecurityState.AUTHORIZED, "owner_return_pending")
                return
            if target == SecurityState.UNKNOWN_PERSON:
                self._safe_transition(SecurityState.WARNING, "unknown_during_pending")
                return
            if self._pending_since is None:
                self._pending_since = now
            elif (now - self._pending_since) >= self.config.protect_threshold_sec:
                self._safe_transition(
                    SecurityState.PROTECTED,
                    f"protect_threshold_{self.config.protect_threshold_sec}s",
                )
            return

        if state == SecurityState.WARNING:
            if target == SecurityState.AUTHORIZED:
                self._absent_since = None
                self._safe_transition(SecurityState.AUTHORIZED, "owner_cleared_warning")
            elif stable_absent:
                self._safe_transition(SecurityState.PROTECTION_PENDING, "warning_cleared")
            return

        if state == SecurityState.PROTECTED:
            if target == SecurityState.AUTHORIZED:
                self._absent_since = None
                self._pending_since = None
                self._safe_transition(SecurityState.AUTHORIZED, "owner_return_protected")
            elif target == SecurityState.UNKNOWN_PERSON:
                self._safe_transition(SecurityState.UNKNOWN_PERSON, "unknown_while_protected")
            elif stable_absent:
                self._safe_transition(SecurityState.NO_PERSON, "protected_empty")
            return

        if state == SecurityState.CAMERA_ERROR:
            self._safe_transition(SecurityState.STARTING, "recover_from_error")
            self._warmup_left = self.config.warmup_frames
            return


# Preferred public name for this phase.
SecurityManager = PresenceService
