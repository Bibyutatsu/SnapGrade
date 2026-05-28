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
from typing import Any

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
    # CoreML YuNet is downloaded but inference still runs through OpenCV's
    # cv2.FaceDetectorYN (ONNX) — switching the runtime needs a Python
    # implementation of YuNet's 12-head anchor decode + NMS, tracked separately.
    "yunet_coreml": ("yunet.mlpackage", f"{MODELS_REPO_RAW}/yunet.mlpackage.zip"),
    "face_landmarker": ("face_landmarker.task", f"{MODELS_REPO_RAW}/face_landmarker.task"),
    # CoreML variants (ANE-accelerated on Apple Silicon).
    "u2netp_coreml": ("u2netp.mlpackage", f"{MODELS_REPO_RAW}/u2netp.mlpackage.zip"),
    "yolo26n_coreml": ("yolo26n.mlpackage", f"{MODELS_REPO_RAW}/yolo26n.mlpackage.zip"),
    "depth_coreml": (
        "depth_anything_v2_small.mlpackage",
        f"{MODELS_REPO_RAW}/depth_anything_v2_small.mlpackage.zip",
    ),
    # ONNX fallbacks (kept for back-compat with existing installs).
    "u2netp": ("u2netp.onnx", f"{MODELS_REPO_RAW}/u2netp.onnx"),
    "yolo26n": ("yolo26n.onnx", f"{MODELS_REPO_RAW}/yolo26n.onnx"),
    "nima": ("nima.mlpackage", f"{MODELS_REPO_RAW}/nima.mlpackage.zip"),
    # HyperIQA (CVPR 2020) — ResNet50-backed NR-IQA. Better correlation with
    # human ratings than NIMA. (TopIQ was the original plan, blocked by a
    # coremltools 9.0 bug with multi-element int casts; HyperIQA's pure
    # conv+linear graph converts cleanly.)
    "hyperiqa": ("hyperiqa.mlpackage", f"{MODELS_REPO_RAW}/hyperiqa.mlpackage.zip"),
    "topiq": ("topiq.mlpackage", f"{MODELS_REPO_RAW}/topiq.mlpackage.zip"),
    # MobileCLIP-S0 — Apple's ANE-friendly CLIP variant. Image tower + text
    # tower are separate .mlpackages so we can load only what's needed.
    "mobileclip_image": (
        "mobileclip_s0_image.mlpackage",
        f"{MODELS_REPO_RAW}/mobileclip_s0_image.mlpackage.zip",
    ),
    "mobileclip_text": (
        "mobileclip_s0_text.mlpackage",
        f"{MODELS_REPO_RAW}/mobileclip_s0_text.mlpackage.zip",
    ),
    "places365": ("places365.mlpackage", f"{MODELS_REPO_RAW}/places365.mlpackage.zip"),
    "places365_labels": ("places365_labels.txt", f"{MODELS_REPO_RAW}/places365_labels.txt"),
}

# Optional models a fresh install can pull in one shot (`snapgrade setup`).
# FaceLandmarker and YuNet are added here so they are downloaded during first setup.
OPTIONAL_MODELS = (
    "u2netp_coreml",
    "yolo26n_coreml",
    "yunet",
    "face_landmarker",
    "depth_coreml",
    "hyperiqa",
    "topiq",
    "nima",
    "places365",
    "places365_labels",
    "mobileclip_image",
    "mobileclip_text",
)


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


_COREML_LOGGED = False


def load_coreml(path: Path | str) -> Any:
    """Load a .mlpackage with ANE-preferred compute units.

    Default `ComputeUnit.ALL` lets CoreML pick the fastest backend per op:
    ANE first, GPU second, CPU last. Override via SNAPGRADE_COMPUTE_UNITS
    ∈ {all, cpu_and_gpu, cpu_and_neural_engine, cpu_only}.
    """
    import coremltools as ct  # type: ignore

    global _COREML_LOGGED
    sel = os.environ.get("SNAPGRADE_COMPUTE_UNITS", "all").lower()
    units = {
        "all": ct.ComputeUnit.ALL,
        "cpu_and_gpu": ct.ComputeUnit.CPU_AND_GPU,
        "cpu_and_neural_engine": ct.ComputeUnit.CPU_AND_NE,
        "cpu_only": ct.ComputeUnit.CPU_ONLY,
    }.get(sel, ct.ComputeUnit.ALL)
    if not _COREML_LOGGED:
        _COREML_LOGGED = True
        import logging

        logging.getLogger("snapgrade").info(
            "CoreML backend ready (compute_units=%s); ANE used when available.", sel
        )
    return ct.models.MLModel(str(path), compute_units=units)


def _download(url: str, dest: Path) -> None:
    curl = shutil.which("curl")
    if curl:
        subprocess.run([curl, "-fsSL", "--retry", "3", "-o", str(dest), url], check=True)
    else:
        urllib.request.urlretrieve(url, dest)
