"""Screenshot / document / photo classifier (tiny MobileNetV3-Small head).

Drop a CoreML model at ~/.blurdetector/models/screendoc.mlpackage (or set
BLURDETECTOR_SCREENDOC_MODEL). The model must emit probs for the three
classes [screenshot, document, photo] in that order.

Falls back to a heuristic when no model is present and the user opts in:
  - very few unique colors (palette < 32) → "screenshot"
  - dominant white + low saturation → "document"
This fallback is conservative (lower confidence) so it doesn't auto-reject
real photos.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_MODEL = None
_LOADED = False
_CLASSES = ("screenshot", "document", "photo")


def _model_path() -> Path | None:
    p = os.environ.get("BLURDETECTOR_SCREENDOC_MODEL")
    if p and Path(p).exists():
        return Path(p)
    default = Path.home() / ".blurdetector" / "models" / "screendoc.mlpackage"
    return default if default.exists() else None


def is_available() -> bool:
    # Heuristic fallback is always available, but the user-facing checklist
    # only offers this when a real model is dropped in place.
    return _model_path() is not None


def _load() -> Any | None:
    global _MODEL, _LOADED
    if _LOADED:
        return _MODEL
    _LOADED = True
    mp = _model_path()
    if not mp:
        return None
    try:
        import coremltools as ct
        _MODEL = ct.models.MLModel(str(mp))
    except Exception:
        _MODEL = None
    return _MODEL


def _heuristic(rgb: np.ndarray) -> dict[str, Any]:
    small = np.asarray(Image.fromarray(rgb).resize((96, 96), Image.BILINEAR))
    quantized = (small // 16).reshape(-1, 3)
    unique = len({tuple(p) for p in quantized})
    sat = float(np.std(small.astype(np.float32), axis=2).mean())
    if unique < 80:
        return {"class": "screenshot", "conf": 0.55, "source": "heuristic"}
    if sat < 8.0 and small.mean() > 200:
        return {"class": "document", "conf": 0.55, "source": "heuristic"}
    return {"class": "photo", "conf": 0.55, "source": "heuristic"}


def analyze(rgb: np.ndarray) -> dict[str, Any]:
    model = _load()
    if model is None:
        return _heuristic(rgb)
    try:
        im = Image.fromarray(rgb).resize((224, 224), Image.BILINEAR)
        x = np.asarray(im, dtype=np.float32) / 255.0
        x = x.transpose(2, 0, 1).astype(np.float32)  # HWC → CHW; CoreML model is NCHW
        out = model.predict({list(model.input_description)[0]: x[None, ...]})
        probs = np.asarray(next(iter(out.values()))).ravel()
        if probs.size != len(_CLASSES):
            return _heuristic(rgb)
        i = int(probs.argmax())
        return {"class": _CLASSES[i], "conf": float(probs[i]), "source": "model",
                "probs": {c: float(p) for c, p in zip(_CLASSES, probs)}}
    except Exception:
        return _heuristic(rgb)
