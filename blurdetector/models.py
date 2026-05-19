"""Lazy on-disk cache for MediaPipe Tasks model files.

Models are tiny (≤ a few MB) and downloaded once into ~/.blurdetector/models/.
Set BLURDETECTOR_MODELS_DIR to override.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

MODELS_DIR = Path(os.environ.get("BLURDETECTOR_MODELS_DIR", Path.home() / ".blurdetector" / "models"))

_REGISTRY = {
    # YuNet — OpenCV's full-scene face detector; handles small faces across
    # scales far better than MediaPipe's selfie-only BlazeFace.
    "yunet": (
        "face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ),
    "face_landmarker": (
        "face_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    ),
}


def ensure(name: str) -> Path:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown model: {name}")
    filename, url = _REGISTRY[name]
    target = MODELS_DIR / filename
    if target.exists() and target.stat().st_size > 0:
        return target
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    # Prefer curl on macOS — the framework Python often doesn't trust the
    # system CA store, so urllib SSL verification fails.
    curl = shutil.which("curl")
    if curl:
        subprocess.run(
            [curl, "-fsSL", "--retry", "3", "-o", str(tmp), url],
            check=True,
        )
    else:
        urllib.request.urlretrieve(url, tmp)
    tmp.rename(target)
    return target
