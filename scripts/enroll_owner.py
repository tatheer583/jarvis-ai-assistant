"""Enroll the authorized owner (Tatheer) for local face verification.

Usage:
  python scripts/enroll_owner.py
  python scripts/enroll_owner.py --samples 10
  python scripts/enroll_owner.py --images path1.jpg path2.jpg

Templates are stored under Data/Security/ (gitignored). Frames are not kept.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Backend.Security.config import load_security_config
from Backend.Security.enrollment import enroll_owner_from_camera, enroll_owner_from_images


def main() -> int:
    parser = argparse.ArgumentParser(description="Enroll Jarvis authorized owner face")
    parser.add_argument("--samples", type=int, default=8, help="Camera samples to capture")
    parser.add_argument("--camera", type=int, default=None, help="Camera index override")
    parser.add_argument("--images", nargs="+", type=Path, help="Enroll from image files")
    args = parser.parse_args()

    cfg = load_security_config()
    print(f"Owner: {cfg.owner_display_name}")
    print(f"Template dir: {cfg.security_dir}")

    if args.images:
        path = enroll_owner_from_images(args.images, cfg)
    else:
        print("Look at the webcam. Capturing face samples...")
        path = enroll_owner_from_camera(
            cfg, samples=args.samples, camera_index=args.camera
        )
    print(f"Enrollment complete: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
