#!/usr/bin/env python3
"""Download MediaPipe model files required by the CV feature extractor.

Run once during Docker build or local setup:

    python scripts/download_models.py

Models are saved to ``models/`` (git-ignored).
"""

import os
import sys
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

MODELS = {
    "pose_landmarker_lite.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "pose_landmarker/pose_landmarker_lite/float16/latest/"
        "pose_landmarker_lite.task"
    ),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "face_landmarker/face_landmarker/float16/latest/"
        "face_landmarker.task"
    ),
}


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in MODELS.items():
        dest = MODELS_DIR / name
        if dest.exists():
            print(f"  skip {name} (already exists)")
            continue
        print(f"  downloading {name} …")
        urllib.request.urlretrieve(url, dest)
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  saved {name} ({size_mb:.1f} MB)")
    print("done")


if __name__ == "__main__":
    main()
