"""Local on-device face detection + owner template matching.

Algorithm
---------
1. Haar cascade face detection (OpenCV, CPU-only).
2. Grayscale crop -> resize 100x100 -> histogram equalization.
3. L2-normalized pixel descriptor (length 10000).
4. Cosine similarity (dot product of unit vectors) vs enrolled templates.
5. Match if best score >= FaceMatchThreshold (default 0.82).

Threshold meaning
-----------------
Score is in roughly [-1, 1]; same-person frontal samples typically score high
(often >0.85). Default 0.82 prefers fewer false authorizations over easy matches.
Lighting, pose, and glasses can lower scores; re-enroll if needed.

No cloud APIs. No raw video storage. Templates are descriptors only (optionally DPAPI).
"""

from __future__ import annotations

import logging
import os
import struct
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("Jarvis.Security.Face")

FACE_SIZE = (100, 100)
TEMPLATE_VERSION = 2


class IdentityResult(str, Enum):
    OWNER = "OWNER"
    UNKNOWN = "UNKNOWN"
    NO_FACE = "NO_FACE"
    NO_TEMPLATE = "NO_TEMPLATE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class VerifyResult:
    identity: IdentityResult
    score: float = 0.0
    faces_found: int = 0
    reason: str = ""


@dataclass(frozen=True)
class QualityResult:
    ok: bool
    reason: str = ""
    brightness: float = 0.0
    blur_var: float = 0.0
    face_size: int = 0


def _try_dpapi_protect(data: bytes) -> bytes:
    """Best-effort Windows DPAPI wrap. Returns original bytes if unavailable."""
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        in_buf = ctypes.create_string_buffer(data)
        blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in), "JarvisOwnerTemplate", None, None, None, 0, ctypes.byref(blob_out)
        ):
            return data
        try:
            protected = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
        return b"DPAPI1" + protected
    except Exception as exc:
        log.debug("DPAPI protect unavailable: %s", exc)
        return data


def _try_dpapi_unprotect(data: bytes) -> bytes:
    if not data.startswith(b"DPAPI1"):
        return data
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        raw = data[6:]
        in_buf = ctypes.create_string_buffer(raw)
        blob_in = DATA_BLOB(len(raw), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            raise OSError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception as exc:
        log.warning("DPAPI unprotect failed: %s", exc)
        raise


def default_template_path(security_dir: Path) -> Path:
    return security_dir / "owner_template.bin"


def _restrict_file_permissions(path: Path) -> None:
    """Best-effort: owner-only ACL on Windows; chmod 0600 elsewhere."""
    try:
        if os.name == "nt":
            import subprocess

            user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
            if user:
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                    check=False,
                    capture_output=True,
                )
        else:
            os.chmod(path, 0o600)
    except Exception as exc:
        log.debug("Could not tighten template permissions: %s", exc)


class FaceVerifier:
    """Haar face detect + cosine similarity against enrolled descriptors."""

    def __init__(
        self,
        template_path: Path,
        *,
        match_threshold: float = 0.82,
        require_enrollment: bool = False,
        min_face_size: int = 80,
        min_brightness: float = 40.0,
        max_brightness: float = 220.0,
        min_laplacian_var: float = 40.0,
    ) -> None:
        self.template_path = template_path
        self.match_threshold = match_threshold
        self.require_enrollment = require_enrollment
        self.min_face_size = min_face_size
        self.min_brightness = min_brightness
        self.max_brightness = max_brightness
        self.min_laplacian_var = min_laplacian_var
        self._cascade: Any = None
        self._templates: list[Any] = []
        self._load_cascade()
        self.reload_templates()

    @property
    def is_enrolled(self) -> bool:
        return len(self._templates) > 0

    @property
    def template_exists_on_disk(self) -> bool:
        return self.template_path.exists()

    def _load_cascade(self) -> None:
        try:
            import cv2

            cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            if not hasattr(cv2, "CascadeClassifier"):
                log.warning("cv2 has no CascadeClassifier; disabling face detection")
                self._cascade = None
                return

            cascade = cv2.CascadeClassifier(str(cascade_path))
            if hasattr(cascade, "empty") and callable(cascade.empty) and cascade.empty():
                raise RuntimeError(f"Failed to load Haar cascade: {cascade_path}")
            self._cascade = cascade
        except Exception as exc:
            log.warning("OpenCV cascade unavailable, face detection disabled: %s", exc)
            self._cascade = None

    def reload_templates(self) -> None:
        self._templates = []
        if not self.template_path.exists():
            log.info("No owner template at %s", self.template_path)
            return
        try:
            import numpy as np

            raw = self.template_path.read_bytes()
            raw = _try_dpapi_unprotect(raw)
            if len(raw) < 16 or raw[:4] != b"JFT2":
                raise ValueError("Unrecognized template format")
            count = struct.unpack_from("<I", raw, 4)[0]
            dim = struct.unpack_from("<I", raw, 8)[0]
            offset = 16
            templates = []
            for _ in range(count):
                need = dim * 4
                chunk = raw[offset : offset + need]
                if len(chunk) != need:
                    raise ValueError("Truncated template payload")
                vec = np.frombuffer(chunk, dtype=np.float32).copy()
                templates.append(vec)
                offset += need
            self._templates = templates
            log.info("Loaded %d owner face template(s)", len(templates))
        except Exception as exc:
            log.error("Failed to load owner template: %s", exc)
            self._templates = []

    def detect_faces(self, frame) -> list[tuple[int, int, int, int]]:
        import cv2

        if frame is None or self._cascade is None:
            return []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(max(40, self.min_face_size // 2), max(40, self.min_face_size // 2)),
        )
        return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]

    def assess_face_quality(self, frame, bbox: tuple[int, int, int, int]) -> QualityResult:
        """Reject unusable faces: small, dark/bright, blurry."""
        import cv2
        import numpy as np

        if frame is None:
            return QualityResult(False, "empty_frame")
        x, y, w, h = bbox
        size = min(w, h)
        if size < self.min_face_size:
            return QualityResult(False, "face_too_small", face_size=size)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        pad = int(0.05 * w)
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(gray.shape[1], x + w + pad)
        y1 = min(gray.shape[0], y + h + pad)
        roi = gray[y0:y1, x0:x1]
        if roi.size == 0:
            return QualityResult(False, "empty_roi", face_size=size)

        brightness = float(np.mean(roi))
        blur_var = float(cv2.Laplacian(roi, cv2.CV_64F).var())
        if brightness < self.min_brightness:
            return QualityResult(False, "too_dark", brightness=brightness, blur_var=blur_var, face_size=size)
        if brightness > self.max_brightness:
            return QualityResult(False, "too_bright", brightness=brightness, blur_var=blur_var, face_size=size)
        if blur_var < self.min_laplacian_var:
            return QualityResult(False, "too_blurry", brightness=brightness, blur_var=blur_var, face_size=size)
        return QualityResult(True, "ok", brightness=brightness, blur_var=blur_var, face_size=size)

    def extract_descriptor(self, frame, bbox: tuple[int, int, int, int] | None = None):
        """Return L2-normalized float32 descriptor, or None."""
        import cv2
        import numpy as np

        if frame is None:
            return None
        if bbox is None:
            faces = self.detect_faces(frame)
            if len(faces) != 1:
                return None
            bbox = faces[0]
        x, y, w, h = bbox
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        pad = int(0.1 * w)
        x0 = max(0, x - pad)
        y0 = max(0, y - pad)
        x1 = min(gray.shape[1], x + w + pad)
        y1 = min(gray.shape[0], y + h + pad)
        roi = gray[y0:y1, x0:x1]
        if roi.size == 0:
            return None
        face = cv2.resize(roi, FACE_SIZE)
        face = cv2.equalizeHist(face)
        vec = face.astype(np.float32).reshape(-1)
        norm = float(np.linalg.norm(vec))
        if norm < 1e-6:
            return None
        return vec / norm

    def best_match_score(self, descriptor) -> float:
        import numpy as np

        if descriptor is None or not self._templates:
            return 0.0
        scores = [float(np.dot(descriptor, t)) for t in self._templates]
        return max(scores) if scores else 0.0

    def verify_owner(self, frame) -> VerifyResult:
        """Owner-vs-unknown verification entry point used by SecurityManager."""
        return self.verify_frame(frame)

    def verify_frame(self, frame) -> VerifyResult:
        try:
            faces = self.detect_faces(frame) if frame is not None else []
            n = len(faces)

            if not self.is_enrolled:
                if self.require_enrollment:
                    if n == 0:
                        return VerifyResult(IdentityResult.NO_FACE, faces_found=0, reason="enrollment_required")
                    return VerifyResult(
                        IdentityResult.UNKNOWN,
                        faces_found=n,
                        reason="enrollment_required",
                    )
                return VerifyResult(
                    IdentityResult.NO_TEMPLATE,
                    faces_found=n,
                    reason="no_owner_template",
                )

            if n == 0:
                return VerifyResult(IdentityResult.NO_FACE, reason="no_face_detected")
            if n > 1:
                return VerifyResult(
                    IdentityResult.UNKNOWN,
                    faces_found=n,
                    reason="multiple_faces",
                )

            bbox = faces[0]
            quality = self.assess_face_quality(frame, bbox)
            if not quality.ok:
                log.debug(
                    "verify quality reject reason=%s brightness=%.1f blur=%.1f size=%d",
                    quality.reason,
                    quality.brightness,
                    quality.blur_var,
                    quality.face_size,
                )
                return VerifyResult(
                    IdentityResult.NO_FACE,
                    faces_found=1,
                    reason=f"poor_quality:{quality.reason}",
                )

            desc = self.extract_descriptor(frame, bbox)
            if desc is None:
                return VerifyResult(IdentityResult.NO_FACE, faces_found=1, reason="descriptor_failed")

            score = self.best_match_score(desc)
            log.debug("verify score=%.4f threshold=%.4f", score, self.match_threshold)
            if score >= self.match_threshold:
                return VerifyResult(
                    IdentityResult.OWNER,
                    score=score,
                    faces_found=1,
                    reason="owner_match",
                )
            return VerifyResult(
                IdentityResult.UNKNOWN,
                score=score,
                faces_found=1,
                reason="below_threshold",
            )
        except Exception as exc:
            log.warning("verify_frame failed: %s", exc)
            return VerifyResult(IdentityResult.ERROR, reason=type(exc).__name__)

    def save_templates(
        self,
        descriptors: list[Any],
        *,
        use_dpapi: bool = True,
        replace: bool = False,
    ) -> Path:
        import numpy as np

        if not descriptors:
            raise ValueError("No descriptors to save")
        if self.template_path.exists() and not replace:
            raise FileExistsError(
                f"Owner template already exists at {self.template_path}. "
                "Pass replace=True / --force to overwrite."
            )
        self.template_path.parent.mkdir(parents=True, exist_ok=True)
        dim = int(descriptors[0].shape[0])
        payload = bytearray()
        payload += b"JFT2"
        payload += struct.pack("<I", len(descriptors))
        payload += struct.pack("<I", dim)
        payload += struct.pack("<I", TEMPLATE_VERSION)
        for d in descriptors:
            arr = np.asarray(d, dtype=np.float32).reshape(-1)
            if arr.shape[0] != dim:
                raise ValueError("Inconsistent descriptor dimensions")
            payload += arr.tobytes()
        data = bytes(payload)
        if use_dpapi:
            data = _try_dpapi_protect(data)
        self.template_path.write_bytes(data)
        _restrict_file_permissions(self.template_path)
        self.reload_templates()
        log.info("Saved %d owner template(s) to %s", len(descriptors), self.template_path)
        return self.template_path

    def delete_template(self) -> bool:
        """Remove local owner template. Returns True if a file was deleted."""
        self._templates = []
        if not self.template_path.exists():
            return False
        self.template_path.unlink()
        log.info("Deleted owner template at %s", self.template_path)
        return True