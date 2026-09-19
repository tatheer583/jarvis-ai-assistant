"""Local person-presence heuristics (motion + contour). No cloud, no frame storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PresenceStatus(str, Enum):
    NO_PERSON = "NO_PERSON"
    PERSON_PRESENT = "PERSON_PRESENT"


@dataclass
class PresenceDetector:
    """Detect likely human presence from successive frames.

    Uses grayscale frame differencing + contour area. Frames are not stored.
    """

    motion_threshold: float = 12.0
    min_contour_area: float = 5000.0
    _prev_gray: Any = field(default=None, repr=False)

    def reset(self) -> None:
        self._prev_gray = None

    def classify(self, frame) -> PresenceStatus:
        return (
            PresenceStatus.PERSON_PRESENT
            if self.person_present(frame)
            else PresenceStatus.NO_PERSON
        )

    def person_present(self, frame) -> bool:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return False

        if frame is None:
            return False

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            _, thresh = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            return any(cv2.contourArea(c) >= self.min_contour_area for c in contours)

        delta = cv2.absdiff(self._prev_gray, gray)
        self._prev_gray = gray
        mean_delta = float(np.mean(delta))

        _, thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)
        thresh = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        large_motion = any(cv2.contourArea(c) >= self.min_contour_area for c in contours)

        if not large_motion and mean_delta < self.motion_threshold:
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)
            return edge_ratio > 0.02

        return large_motion or mean_delta >= self.motion_threshold
