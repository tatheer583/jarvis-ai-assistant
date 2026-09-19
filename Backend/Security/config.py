"""Security configuration loaded from .env."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"
SECURITY_DIR = BASE_DIR / "Data" / "Security"
DISABLE_FLAG_PATH = SECURITY_DIR / "DISABLE"

DEFAULT_OWNER = "Tatheer"
DEFAULT_GREETING = (
    "Hi sir Tatheer, welcome back. How are you? What would you like to do today?"
)
DEFAULT_UNAUTHORIZED = (
    "Sorry, you are not Tatheer. This computer is restricted."
)


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None and str(value).strip() else default
    except (TypeError, ValueError):
        return default


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(float(value)) if value is not None and str(value).strip() else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SecurityConfig:
    enabled: bool = True
    camera_enabled: bool = True
    enforce: bool = False  # observe-only until you enable gating
    camera_index: int = 0
    frame_interval_sec: float = 0.5  # PresenceCheckInterval
    warmup_frames: int = 5
    absence_timeout_sec: float = 25.0  # owner absent -> PROTECTION_PENDING
    unknown_person_timeout_sec: float = 20.0
    absence_stable_frames: int = 10
    presence_stable_frames: int = 3
    warning_grace_sec: float = 10.0
    protect_threshold_sec: float = 15.0  # pending -> PROTECTED
    greeting_cooldown_sec: float = 300.0
    warning_cooldown_sec: float = 30.0
    owner_display_name: str = DEFAULT_OWNER
    authorized_greeting: str = DEFAULT_GREETING
    unauthorized_message: str = DEFAULT_UNAUTHORIZED
    warning_message: str = (
        "Unauthorized presence detected. Please step away or wait for the owner."
    )
    disable_phrase: str = "disable security override"
    motion_threshold: float = 12.0
    min_contour_area: float = 5000.0
    face_match_threshold: float = 0.82
    require_face_enrollment: bool = False
    face_stable_frames: int = 2
    face_min_size: int = 80
    face_min_brightness: float = 40.0
    face_max_brightness: float = 220.0
    face_min_laplacian_var: float = 40.0
    security_dir: Path = SECURITY_DIR

    @property
    def owner_name(self) -> str:
        return self.owner_display_name

    @property
    def presence_check_interval(self) -> float:
        return self.frame_interval_sec

    @property
    def disable_flag_path(self) -> Path:
        return self.security_dir / "DISABLE"

    @property
    def log_path(self) -> Path:
        return self.security_dir / "security.log"

    @property
    def owner_template_path(self) -> Path:
        return self.security_dir / "owner_template.bin"

    def is_manually_disabled(self) -> bool:
        return self.disable_flag_path.exists()

    def effective_enabled(self) -> bool:
        return self.enabled and not self.is_manually_disabled()


def load_security_config(env_path: Path | None = None) -> SecurityConfig:
    env = dotenv_values(str(env_path or ENV_PATH))
    owner = (
        env.get("OwnerName")
        or env.get("OwnerDisplayName")
        or DEFAULT_OWNER
    ).strip() or DEFAULT_OWNER
    interval = env.get("PresenceCheckInterval") or env.get("SecurityFrameIntervalSec")
    greeting = (
        env.get("AuthorizedGreeting") or DEFAULT_GREETING
    ).strip()
    unauthorized = (
        env.get("UnauthorizedMessage") or DEFAULT_UNAUTHORIZED
    ).strip()
    return SecurityConfig(
        enabled=_as_bool(env.get("SecurityEnabled"), True),
        camera_enabled=_as_bool(env.get("CameraEnabled"), True),
        enforce=_as_bool(env.get("SecurityEnforce"), False),
        camera_index=_as_int(env.get("CameraIndex"), 0),
        frame_interval_sec=_as_float(interval, 0.5),
        warmup_frames=_as_int(env.get("SecurityWarmupFrames"), 5),
        absence_timeout_sec=_as_float(
            env.get("AbsenceTimeout") or env.get("AbsenceTimeoutSec"), 25.0
        ),
        unknown_person_timeout_sec=_as_float(
            env.get("UnknownPersonTimeout") or env.get("UnknownPersonTimeoutSec"), 20.0
        ),
        absence_stable_frames=_as_int(env.get("AbsenceStableFrames"), 10),
        presence_stable_frames=_as_int(env.get("PresenceStableFrames"), 3),
        warning_grace_sec=_as_float(env.get("WarningGraceSec"), 10.0),
        protect_threshold_sec=_as_float(env.get("ProtectThresholdSec"), 15.0),
        greeting_cooldown_sec=_as_float(env.get("GreetingCooldownSec"), 300.0),
        warning_cooldown_sec=_as_float(env.get("WarningCooldownSec"), 30.0),
        owner_display_name=owner,
        authorized_greeting=greeting,
        unauthorized_message=unauthorized,
        warning_message=(
            env.get("SecurityWarningMessage")
            or "Unauthorized presence detected. Please step away or wait for the owner."
        ).strip(),
        disable_phrase=(
            env.get("SecurityDisablePhrase") or "disable security override"
        ).strip().lower(),
        motion_threshold=_as_float(env.get("SecurityMotionThreshold"), 12.0),
        min_contour_area=_as_float(env.get("SecurityMinContourArea"), 5000.0),
        face_match_threshold=_as_float(env.get("FaceMatchThreshold"), 0.82),
        require_face_enrollment=_as_bool(env.get("RequireFaceEnrollment"), False),
        face_stable_frames=_as_int(env.get("FaceStableFrames"), 2),
        face_min_size=_as_int(env.get("FaceMinSize"), 80),
        face_min_brightness=_as_float(env.get("FaceMinBrightness"), 40.0),
        face_max_brightness=_as_float(env.get("FaceMaxBrightness"), 220.0),
        face_min_laplacian_var=_as_float(env.get("FaceMinLaplacianVar"), 40.0),
        security_dir=SECURITY_DIR,
    )
