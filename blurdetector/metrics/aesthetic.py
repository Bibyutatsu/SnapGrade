"""NIMA aesthetic scoring via CoreML.

The CoreML model is not bundled — the user supplies one. We expect a model
that takes a 224x224 RGB image (mean/std normalized like ImageNet) and emits
a 10-bin distribution; score = sum(i * p_i) / 9 → [0,1].

Set BLURDETECTOR_NIMA_MODEL to the .mlmodelc/.mlpackage path. If unset or the
model fails to load, scoring returns None and the rest of the pipeline carries
on unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

_MODEL = None
_LOADED = False
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _load() -> object | None:
    global _MODEL, _LOADED
    if _LOADED:
        return _MODEL
    _LOADED = True
    path = os.environ.get("BLURDETECTOR_NIMA_MODEL")
    if not path:
        default = Path.home() / ".blurdetector" / "models" / "nima.mlpackage"
        if default.exists():
            path = str(default)
    if not path or not Path(path).exists():
        return None
    try:
        import coremltools as ct

        _MODEL = ct.models.MLModel(path)
    except Exception:
        _MODEL = None
    return _MODEL


def _preprocess(rgb: np.ndarray) -> np.ndarray:
    """Return NCHW float32 array. PyTorch MobileNetV2 (converted via traced
    `torch.jit.trace`) expects channels-first; passing HWC silently runs the
    model on transposed pixels and produces garbage scores."""
    im = Image.fromarray(rgb).resize((224, 224), Image.BILINEAR)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = (arr - _MEAN) / _STD
    return arr.transpose(2, 0, 1).astype(np.float32)


def score(rgb: np.ndarray) -> float | None:
    model = _load()
    if model is None:
        return None
    try:
        x = _preprocess(rgb)
        out = model.predict({list(model.input_description)[0]: x[None, ...]})
        # Accept either a 10-bin distribution or a scalar; normalize to [0,1].
        first = next(iter(out.values()))
        arr = np.asarray(first).ravel()
        if arr.size == 10:
            # Apply softmax in case the model emits raw logits (the
            # titu1994/neural-image-assessment Keras checkpoints emit probs,
            # but PyTorch ports usually leave the head as a Linear layer).
            if arr.min() < 0 or arr.max() > 1.5:
                arr = np.exp(arr - arr.max())
                arr = arr / arr.sum()
            bins = np.arange(1, 11, dtype=np.float32)
            mean = float((arr * bins).sum() / max(arr.sum(), 1e-6))
            return max(0.0, min(1.0, (mean - 1.0) / 9.0))
        if arr.size == 1:
            return max(0.0, min(1.0, float(arr[0])))
        return None
    except Exception:
        return None
