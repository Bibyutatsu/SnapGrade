"""Lazy on-disk cache for MediaPipe Tasks model files.

Models are tiny (≤ a few MB) and downloaded once into ~/.snapgrade/models/.
Set SNAPGRADE_MODELS_DIR to override.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

MODELS_DIR = Path(os.environ.get("SNAPGRADE_MODELS_DIR", Path.home() / ".snapgrade" / "models"))

# Community model host. Override the whole base with SNAPGRADE_MODELS_REPO
# (e.g. a fork or a local mirror) without touching individual entries.
MODELS_REPO_RAW = os.environ.get(
    "SNAPGRADE_MODELS_REPO",
    "https://raw.githubusercontent.com/Bibyutatsu/macos-computer-vision-models/main/models",
)

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
    "u2netp": ("u2netp.onnx", f"{MODELS_REPO_RAW}/u2netp.onnx"),
    "yolov8n": ("yolov8n.mlpackage", f"{MODELS_REPO_RAW}/yolov8n.mlpackage.zip"),
    "nima": ("nima.mlpackage", f"{MODELS_REPO_RAW}/nima.mlpackage.zip"),
    "places365": ("places365.mlpackage", f"{MODELS_REPO_RAW}/places365.mlpackage.zip"),
    "places365_labels": ("places365_labels.txt", f"{MODELS_REPO_RAW}/places365_labels.txt"),
    "screendoc": ("screendoc.mlpackage", f"{MODELS_REPO_RAW}/screendoc.mlpackage.zip"),
}

# Optional models a fresh install can pull in one shot (`snapgrade setup`).
# YuNet + face_landmarker auto-download on first analyze, so they're excluded.
OPTIONAL_MODELS = ("u2netp", "yolov8n", "nima", "places365", "places365_labels", "screendoc")


def is_present(name: str) -> bool:
    """True if the model file/dir already exists on disk (no download)."""
    if name not in _REGISTRY:
        return False
    target = MODELS_DIR / _REGISTRY[name][0]
    return target.exists() and (target.is_dir() or target.stat().st_size > 0)


def ensure(name: str) -> Path:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown model: {name}")
    filename, url = _REGISTRY[name]
    target = MODELS_DIR / filename
    if target.exists() and (target.is_dir() or target.stat().st_size > 0):
        return target
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    if url.endswith(".zip"):
        zip_target = MODELS_DIR / f"{filename}.zip"
        tmp = zip_target.with_suffix(".part")
        curl = shutil.which("curl")
        if curl:
            subprocess.run(
                [curl, "-fsSL", "--retry", "3", "-o", str(tmp), url],
                check=True,
            )
        else:
            urllib.request.urlretrieve(url, tmp)
        tmp.rename(zip_target)
        
        import zipfile
        with zipfile.ZipFile(zip_target, "r") as zip_ref:
            zip_ref.extractall(MODELS_DIR)
        zip_target.unlink()
    else:
        tmp = target.with_suffix(target.suffix + ".part")
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
