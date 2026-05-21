"""Salient subject segmentation via U²-Netp ONNX (~4.6 MB).

Drop the model at ~/.snapgrade/models/u2netp.onnx
(or set SNAPGRADE_U2NETP_MODEL).

Returns: foreground mask coverage + bounding box of salient subject + a crude
'bokeh score' (mean BG blur / FG sharpness, when computable).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_SESSION = None
_LOADED = False
_IS_COREML = False
_IN_SIZE = 320


def _model_path() -> Path | None:
    p = os.environ.get("SNAPGRADE_U2NETP_MODEL")
    if p and Path(p).exists():
        return Path(p)
    models_dir = Path.home() / ".snapgrade" / "models"
    for candidate in (models_dir / "u2netp.mlpackage", models_dir / "u2netp.onnx"):
        if candidate.exists():
            return candidate
    return None


def is_available() -> bool:
    return _model_path() is not None


def _load() -> Any | None:
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


def analyze(rgb: np.ndarray) -> dict[str, Any]:
    sess = _load()
    if sess is None:
        return {}
    try:
        h0, w0 = rgb.shape[:2]
        im = Image.fromarray(rgb).resize((_IN_SIZE, _IN_SIZE), Image.BILINEAR)
        arr = np.asarray(im, dtype=np.float32) / 255.0
        arr = (arr - 0.485) / 0.229  # U²-Net uses a single mean/std
        x = arr.transpose(2, 0, 1)[None, ...].astype(np.float32)
        if _IS_COREML:
            out = sess.predict({"input_1": x})
            mask = np.asarray(list(out.values())[0]).squeeze()
        else:
            out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
            mask = np.asarray(out).squeeze()
        mask = (mask - mask.min()) / max(mask.max() - mask.min(), 1e-6)
        binary = mask > 0.5
        coverage = float(binary.mean())
        if coverage > 0:
            ys, xs = np.where(binary)
            y0, y1 = int(ys.min() * h0 / _IN_SIZE), int(ys.max() * h0 / _IN_SIZE)
            x0, x1 = int(xs.min() * w0 / _IN_SIZE), int(xs.max() * w0 / _IN_SIZE)
            bbox = [x0, y0, x1, y1]
        else:
            bbox = None
        return {"coverage": coverage, "bbox": bbox}
    except Exception:
        return {}
