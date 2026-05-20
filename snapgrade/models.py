"""Lazy on-disk cache for MediaPipe Tasks model files.

Models are tiny (≤ a few MB) and downloaded once into ~/.snapgrade/models/.
Set SNAPGRADE_MODELS_DIR to override.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

MODELS_DIR = Path(os.environ.get("SNAPGRADE_MODELS_DIR", Path.home() / ".snapgrade" / "models"))

# Expected SHA-256 of each downloaded artifact, bundled in-repo so a compromised
# model host can't supply a matching digest. Missing entries → no verification
# (logged), present-but-mismatched → hard failure.
_MANIFEST_PATH = Path(__file__).with_name("models_manifest.json")


class ChecksumError(RuntimeError):
    """A downloaded model artifact failed SHA-256 verification."""


def _expected_digests() -> dict[str, str]:
    try:
        return json.loads(_MANIFEST_PATH.read_text()).get("models", {})
    except (OSError, ValueError):
        return {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify(name: str, artifact: Path) -> None:
    """Raise ChecksumError if `artifact` doesn't match the bundled manifest.

    Set SNAPGRADE_SKIP_CHECKSUM=1 to bypass (e.g. when bootstrapping a new
    model whose digest isn't pinned yet).
    """
    if os.environ.get("SNAPGRADE_SKIP_CHECKSUM"):
        return
    expected = _expected_digests().get(name)
    if not expected:
        return  # unpinned model — nothing to verify against
    actual = _sha256(artifact)
    if actual != expected:
        artifact.unlink(missing_ok=True)
        raise ChecksumError(
            f"Checksum mismatch for model '{name}': expected {expected}, got {actual}. "
            f"Refusing to load a tampered or corrupted artifact ({artifact.name})."
        )

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
    # YOLO26n (ONNX) supersedes YOLOv8n; legacy entry kept for back-compat.
    "yolo26n": ("yolo26n.onnx", f"{MODELS_REPO_RAW}/yolo26n.onnx"),
    "yolov8n": ("yolov8n.mlpackage", f"{MODELS_REPO_RAW}/yolov8n.mlpackage.zip"),
    "nima": ("nima.mlpackage", f"{MODELS_REPO_RAW}/nima.mlpackage.zip"),
    "places365": ("places365.mlpackage", f"{MODELS_REPO_RAW}/places365.mlpackage.zip"),
    "places365_labels": ("places365_labels.txt", f"{MODELS_REPO_RAW}/places365_labels.txt"),
    "depth": ("depth_anything_v2_small.onnx", f"{MODELS_REPO_RAW}/depth_anything_v2_small.onnx"),
}

# Optional models a fresh install can pull in one shot (`snapgrade setup`).
# YuNet + face_landmarker auto-download on first analyze, so they're excluded.
OPTIONAL_MODELS = ("u2netp", "yolo26n", "nima", "places365", "places365_labels", "depth")


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
        _download(url, tmp)
        tmp.rename(zip_target)
        # Verify the .zip before extracting — never unpack an unverified archive.
        _verify(name, zip_target)

        import zipfile
        with zipfile.ZipFile(zip_target, "r") as zip_ref:
            zip_ref.extractall(MODELS_DIR)
        zip_target.unlink()
    else:
        tmp = target.with_suffix(target.suffix + ".part")
        _download(url, tmp)
        _verify(name, tmp)
        tmp.rename(target)
    return target


def _download(url: str, dest: Path) -> None:
    curl = shutil.which("curl")
    if curl:
        subprocess.run([curl, "-fsSL", "--retry", "3", "-o", str(dest), url], check=True)
    else:
        urllib.request.urlretrieve(url, dest)
