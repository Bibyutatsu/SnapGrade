"""Aesthetic scoring — HyperIQA preferred, NIMA fallback.

HyperIQA (CVPR 2020, ResNet50 + hyper-network head) correlates ~0.85 SRCC on
LIVE-C vs NIMA's ~0.65. (TopIQ was the original target but is blocked by a
coremltools 9.0 graph bug with multi-element int casts; revisit when fixed.)
Both backends are optional: if neither is on disk, `score()` returns
`(None, None)` and the rest of the pipeline carries on.

Override paths via SNAPGRADE_HYPERIQA_MODEL / SNAPGRADE_NIMA_MODEL. Both env
vars take precedence over the auto-downloaded copy under ~/.snapgrade/models/.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

_NIMA_MODEL = None
_HYPERIQA_MODEL = None
_NIMA_LOADED = False
_HYPERIQA_LOADED = False

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _load_hyperiqa() -> object | None:
    global _HYPERIQA_MODEL, _HYPERIQA_LOADED
    if _HYPERIQA_LOADED:
        return _HYPERIQA_MODEL
    _HYPERIQA_LOADED = True
    path = os.environ.get("SNAPGRADE_HYPERIQA_MODEL")
    if not path:
        try:
            from .. import models
            path = str(models.ensure("hyperiqa"))
        except Exception:
            default = Path.home() / ".snapgrade" / "models" / "hyperiqa.mlpackage"
            if default.exists():
                path = str(default)
    if not path or not Path(path).exists():
        return None
    try:
        from .. import models as _m
        _HYPERIQA_MODEL = _m.load_coreml(path)
    except Exception:
        _HYPERIQA_MODEL = None
    return _HYPERIQA_MODEL


def _load_nima() -> object | None:
    global _NIMA_MODEL, _NIMA_LOADED
    if _NIMA_LOADED:
        return _NIMA_MODEL
    _NIMA_LOADED = True
    path = os.environ.get("SNAPGRADE_NIMA_MODEL")
    if not path:
        try:
            from .. import models
            path = str(models.ensure("nima"))
        except Exception:
            default = Path.home() / ".snapgrade" / "models" / "nima.mlpackage"
            if default.exists():
                path = str(default)
    if not path or not Path(path).exists():
        return None
    try:
        from .. import models as _m
        _NIMA_MODEL = _m.load_coreml(path)
    except Exception:
        _NIMA_MODEL = None
    return _NIMA_MODEL


def _preprocess(rgb: np.ndarray, size: int = 224) -> np.ndarray:
    """ImageNet-normalized NCHW float32. NIMA + HyperIQA both use this convention."""
    im = Image.fromarray(rgb).resize((size, size), Image.BILINEAR)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = (arr - _MEAN) / _STD
    return arr.transpose(2, 0, 1).astype(np.float32)


def _score_hyperiqa(model: object, rgb: np.ndarray) -> float | None:
    # HyperIQA expects 224×224 ImageNet-normalized (single-crop variant — the
    # converted CoreML graph hard-codes num_crop=1, see convert_hyperiqa.py).
    try:
        x = _preprocess(rgb, size=224)
        out = model.predict({list(model.input_description)[0]: x[None, ...]})  # type: ignore[attr-defined]
        first = next(iter(out.values()))
        arr = np.asarray(first).ravel()
        if arr.size == 1:
            return max(0.0, min(1.0, float(arr[0])))
        return None
    except Exception:
        return None


def _score_nima(model: object, rgb: np.ndarray) -> float | None:
    try:
        x = _preprocess(rgb, size=224)
        out = model.predict({list(model.input_description)[0]: x[None, ...]})  # type: ignore[attr-defined]
        first = next(iter(out.values()))
        arr = np.asarray(first).ravel()
        if arr.size == 10:
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


def score(rgb: np.ndarray) -> tuple[float | None, str | None]:
    """Return `(score in [0,1], source)`. Source ∈ {"hyperiqa","nima",None}."""
    m = _load_hyperiqa()
    if m is not None:
        s = _score_hyperiqa(m, rgb)
        if s is not None:
            return s, "hyperiqa"
    m = _load_nima()
    if m is not None:
        s = _score_nima(m, rgb)
        if s is not None:
            return s, "nima"
    return None, None
