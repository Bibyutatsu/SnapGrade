"""Monocular depth via Depth-Anything-V2-Small (ONNX, ~99 MB, opt-in).

Drop the model at ~/.snapgrade/models/depth_anything_v2_small.onnx (or set
SNAPGRADE_DEPTH_MODEL). `is_available()` is False when absent and analyze()
returns {} — so the rest of the pipeline is unaffected.

Primary use: catch the "subject out of focus" failure mode that fools a plain
sharpness metric. We split the frame into near (foreground) and far
(background) by the median predicted depth, then compare local sharpness in
each. A soft foreground in front of a sharp background means the camera locked
focus on the wrong plane.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

_SESSION = None
_LOADED = False
_IS_COREML = False
_IN = 518  # multiple of 14, the model's patch size
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# A foreground is "soft" below this Laplacian variance, and we only call it a
# focus miss when the background is at least this much sharper.
_NEAR_SOFT_MAX = 200.0
_FAR_OVER_NEAR = 1.3


def _model_path() -> Path | None:
    p = os.environ.get("SNAPGRADE_DEPTH_MODEL")
    if p and Path(p).exists():
        return Path(p)
    models_dir = Path.home() / ".snapgrade" / "models"
    for candidate in (
        models_dir / "depth_anything_v2_small.mlpackage",
        models_dir / "depth_anything_v2_small.onnx",
    ):
        if candidate.exists():
            return candidate
    return None


def is_available() -> bool:
    return _model_path() is not None


def _load():
    global _SESSION, _LOADED, _IS_COREML
    if _LOADED:
        return _SESSION
    _LOADED = True
    mp = _model_path()
    if not mp:
        return None
    try:
        if mp.is_dir():
            from .. import models as _m
            _SESSION = _m.load_coreml(mp)
            _IS_COREML = True
        else:
            import onnxruntime as ort
            _SESSION = ort.InferenceSession(str(mp), providers=["CPUExecutionProvider"])
            _IS_COREML = False
    except Exception:
        _SESSION = None
    return _SESSION


def _depth_map(rgb: np.ndarray) -> np.ndarray | None:
    sess = _load()
    if sess is None:
        return None
    import cv2

    im = cv2.resize(rgb, (_IN, _IN), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
    x = ((im - _MEAN) / _STD).transpose(2, 0, 1)[None].astype(np.float32)
    if _IS_COREML:
        out = sess.predict({"pixel_values": x})
        return np.asarray(list(out.values())[0])[0]  # HxW relative depth, higher = nearer
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    return np.asarray(out)[0]  # HxW relative depth, higher = nearer


def analyze(rgb: np.ndarray) -> dict[str, Any]:
    """Return depth-derived focus signals, or {} when the model is absent."""
    depth = _depth_map(rgb)
    if depth is None:
        return {}
    import cv2

    gray = cv2.cvtColor(cv2.resize(rgb, (_IN, _IN)), cv2.COLOR_RGB2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)

    median = float(np.median(depth))
    near = depth >= median   # foreground
    far = depth < median     # background
    near_sharp = float(lap[near].var()) if near.any() else 0.0
    far_sharp = float(lap[far].var()) if far.any() else 0.0

    # Focus landed on the background: foreground soft, background sharper.
    focus_on_background = (
        near_sharp < _NEAR_SOFT_MAX
        and far_sharp > near_sharp * _FAR_OVER_NEAR
    )
    # Depth spread normalized — a proxy for shallow depth-of-field / bokeh.
    depth_range = float(depth.max() - depth.min())

    return {
        "near_sharpness": near_sharp,
        "far_sharpness": far_sharp,
        "focus_on_background": bool(focus_on_background),
        "depth_range": depth_range,
        "near_far_ratio": float(far_sharp / (near_sharp + 1e-6)),
    }
