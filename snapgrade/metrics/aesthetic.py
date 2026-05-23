"""Aesthetic scoring — TopIQ preferred, HyperIQA secondary, NIMA fallback.

TopIQ (CVPR 2024, coarse-to-fine semantic attention) correlates ~0.85+ SRCC on AVA/KonIQ-10k
and is highly efficient. All backends are optional: if none are on disk, `score()` returns
`(None, None)` and the rest of the pipeline carries on.

Override paths via SNAPGRADE_TOPIQ_MODEL / SNAPGRADE_HYPERIQA_MODEL / SNAPGRADE_NIMA_MODEL.
These env vars take precedence over the auto-downloaded copy under ~/.snapgrade/models/.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

_TOPIQ_MODEL = None
_HYPERIQA_MODEL = None
_NIMA_MODEL = None

_TOPIQ_LOADED = False
_HYPERIQA_LOADED = False
_NIMA_LOADED = False

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _load_topiq() -> object | None:
    global _TOPIQ_MODEL, _TOPIQ_LOADED
    if _TOPIQ_LOADED:
        return _TOPIQ_MODEL
    _TOPIQ_LOADED = True
    path = os.environ.get("SNAPGRADE_TOPIQ_MODEL")
    if not path:
        try:
            from .. import models
            path = str(models.ensure("topiq"))
        except Exception:
            default = Path.home() / ".snapgrade" / "models" / "topiq.mlpackage"
            if default.exists():
                path = str(default)
    if not path or not Path(path).exists():
        return None
    try:
        from .. import models as _m
        _TOPIQ_MODEL = _m.load_coreml(path)
    except Exception:
        _TOPIQ_MODEL = None
    return _TOPIQ_MODEL


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
    """ImageNet-normalized NCHW float32. NIMA, HyperIQA, and TopIQ use this convention."""
    im = Image.fromarray(rgb).resize((size, size), Image.BILINEAR)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    arr = (arr - _MEAN) / _STD
    return arr.transpose(2, 0, 1).astype(np.float32)


def _score_topiq(model: object, rgb: np.ndarray) -> float | None:
    # TopIQ expects 384×384 ImageNet-normalized input and returns a single scalar score in [0, 1].
    try:
        x = _preprocess(rgb, size=384)
        out = model.predict({list(model.input_description)[0]: x[None, ...]})  # type: ignore[attr-defined]
        first = next(iter(out.values()))
        arr = np.asarray(first).ravel()
        if arr.size == 1:
            return max(0.0, min(1.0, float(arr[0])))
        return None
    except Exception:
        return None


def _score_hyperiqa(model: object, rgb: np.ndarray) -> float | None:
    # HyperIQA expects 224×224 ImageNet-normalized (single-crop variant).
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
    """Return `(score in [0,1], source)`. Source ∈ {"topiq", "hyperiqa", "nima", None}."""
    m = _load_topiq()
    if m is not None:
        s = _score_topiq(m, rgb)
        if s is not None:
            return s, "topiq"
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
