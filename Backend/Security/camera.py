"""Local webcam access. Frames are never written to disk."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("Jarvis.Security.Camera")


class CameraError(Exception):
    pass


class CameraWorker:
    """Thin OpenCV VideoCapture wrapper."""

    def __init__(self, camera_index: int = 0) -> None:
        self.camera_index = camera_index
        self._cap: Any = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and bool(self._cap.isOpened())

    def open(self) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise CameraError(
                "opencv-python is required for security presence detection"
            ) from exc

        self.close()
        cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise CameraError(f"Unable to open camera index {self.camera_index}")
        # Prefer modest resolution for CPU/privacy.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap = cap
        log.info("Camera %s opened", self.camera_index)

    def read(self):
        """Return BGR frame ndarray or None. Caller must discard after use."""
        if not self.is_open:
            raise CameraError("Camera is not open")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        return frame

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as exc:
                log.warning("Camera release failed: %s", exc)
            self._cap = None
            log.info("Camera closed")
