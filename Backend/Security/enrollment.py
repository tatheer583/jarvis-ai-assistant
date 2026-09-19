"""Owner enrollment helpers — capture local face descriptors only."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from Backend.Security.camera import CameraError, CameraWorker
from Backend.Security.config import SecurityConfig, load_security_config
from Backend.Security.face_verifier import FaceVerifier, default_template_path
from Backend.Security.log import log_security_event

log = logging.getLogger("Jarvis.Security.Enroll")

ProgressFn = Callable[[str], None]


class EnrollmentError(Exception):
    """Enrollment failed (quality / samples / camera)."""


class EnrollmentExistsError(EnrollmentError):
    """Template already exists and replace was not requested."""


def _emit(progress: ProgressFn | None, message: str) -> None:
    log.info("%s", message)
    if progress:
        try:
            progress(message)
        except Exception:
            pass


def _build_verifier(cfg: SecurityConfig) -> FaceVerifier:
    return FaceVerifier(
        default_template_path(cfg.security_dir),
        match_threshold=cfg.face_match_threshold,
        require_enrollment=cfg.require_face_enrollment,
        min_face_size=cfg.face_min_size,
        min_brightness=cfg.face_min_brightness,
        max_brightness=cfg.face_max_brightness,
        min_laplacian_var=cfg.face_min_laplacian_var,
    )


def enroll_owner_from_camera(
    config: SecurityConfig | None = None,
    *,
    samples: int = 8,
    camera_index: int | None = None,
    timeout_sec: float = 60.0,
    replace: bool = False,
    progress: ProgressFn | None = None,
) -> Path:
    """Capture ``samples`` good face descriptors from the webcam and store locally."""
    cfg = config or load_security_config()
    index = cfg.camera_index if camera_index is None else camera_index
    verifier = _build_verifier(cfg)
    template_path = verifier.template_path

    if template_path.exists() and not replace:
        raise EnrollmentExistsError(
            f"Owner template already exists at {template_path}. Re-run with replace=True / --force."
        )

    camera = CameraWorker(index)
    descriptors = []
    min_needed = max(3, samples // 2)
    try:
        _emit(progress, "Starting face enrollment.")
        _emit(progress, "Please look at the camera.")
        camera.open()
        deadline = time.monotonic() + timeout_sec
        while len(descriptors) < samples and time.monotonic() < deadline:
            frame = camera.read()
            if frame is None:
                time.sleep(0.1)
                continue
            faces = verifier.detect_faces(frame)
            if not faces:
                del frame
                time.sleep(0.15)
                continue
            if len(faces) > 1:
                _emit(progress, "Multiple faces detected. Only one person should be visible.")
                del frame
                time.sleep(0.2)
                continue

            _emit(progress, "Face detected.")
            bbox = faces[0]
            quality = verifier.assess_face_quality(frame, bbox)
            if not quality.ok:
                log.debug("Enrollment sample rejected: %s", quality.reason)
                del frame
                time.sleep(0.15)
                continue

            desc = verifier.extract_descriptor(frame, bbox)
            del frame
            if desc is None:
                continue
            descriptors.append(desc)
            _emit(progress, f"Sample captured. ({len(descriptors)}/{samples})")
            time.sleep(0.35)
    finally:
        camera.close()

    if len(descriptors) < min_needed:
        raise EnrollmentError(
            f"Enrollment failed: only captured {len(descriptors)} good face samples "
            f"(need at least {min_needed}). Improve lighting and face the camera."
        )

    path = verifier.save_templates(descriptors, use_dpapi=True, replace=True)
    log_security_event(
        cfg.log_path,
        event="owner_enrolled",
        reason="camera_enrollment",
        sample_count=len(descriptors),
    )
    _emit(progress, "Enrollment completed successfully.")
    return path


def enroll_owner_from_images(
    image_paths: list[Path],
    config: SecurityConfig | None = None,
    *,
    replace: bool = False,
    progress: ProgressFn | None = None,
) -> Path:
    """Enroll from local image files (still no cloud upload)."""
    import cv2

    cfg = config or load_security_config()
    verifier = _build_verifier(cfg)
    if verifier.template_path.exists() and not replace:
        raise EnrollmentExistsError(
            f"Owner template already exists at {verifier.template_path}. Use replace=True / --force."
        )

    _emit(progress, "Starting face enrollment.")
    descriptors = []
    for path in image_paths:
        img = cv2.imread(str(path))
        if img is None:
            log.warning("Skipping unreadable image: %s", path)
            continue
        faces = verifier.detect_faces(img)
        if len(faces) != 1:
            log.warning("Skipping image (need exactly one face): %s faces=%s", path, len(faces))
            continue
        quality = verifier.assess_face_quality(img, faces[0])
        if not quality.ok:
            log.warning("Skipping poor-quality image %s: %s", path, quality.reason)
            continue
        desc = verifier.extract_descriptor(img, faces[0])
        if desc is None:
            continue
        descriptors.append(desc)
        _emit(progress, f"Sample captured. ({len(descriptors)})")

    if len(descriptors) < 1:
        raise EnrollmentError("No usable faces found in provided images")

    path = verifier.save_templates(descriptors, use_dpapi=True, replace=True)
    log_security_event(
        cfg.log_path,
        event="owner_enrolled",
        reason="image_enrollment",
        sample_count=len(descriptors),
    )
    _emit(progress, "Enrollment completed successfully.")
    return path


def reset_owner_enrollment(config: SecurityConfig | None = None) -> bool:
    """Delete the local owner template. Returns True if a file was removed."""
    cfg = config or load_security_config()
    verifier = _build_verifier(cfg)
    deleted = verifier.delete_template()
    if deleted:
        log_security_event(cfg.log_path, event="owner_enrollment_reset", reason="manual_reset")
    return deleted