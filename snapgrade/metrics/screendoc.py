"""Screenshot / document / photo classifier (tiny MobileNetV3-Small head).

Drop a CoreML model at ~/.snapgrade/models/screendoc.mlpackage (or set
SNAPGRADE_SCREENDOC_MODEL). The model must emit probs for the three
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

# Only treat a non-photo classification as actionable above this confidence.
# The shipped model's "photo" class is trained on synthetic color-fields, not
# real DSLR frames, so it over-fires on real photos — keep this high and do
# NOT wire screendoc into decide.py until the model is retrained on real data.
SCREENDOC_MIN_CONF = 0.90


def is_confident(result: dict[str, Any]) -> bool:
    """True only for a high-confidence screenshot/document call (never 'photo')."""
    return (
        isinstance(result, dict)
        and result.get("class") in ("screenshot", "document")
        and float(result.get("conf", 0.0)) >= SCREENDOC_MIN_CONF
    )


def _model_path() -> Path | None:
    p = os.environ.get("SNAPGRADE_SCREENDOC_MODEL")
    if p and Path(p).exists():
        return Path(p)
    default = Path.home() / ".snapgrade" / "models" / "screendoc.mlpackage"
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
        raw = np.asarray(next(iter(out.values()))).ravel()
        if raw.size != len(_CLASSES):
            return _heuristic(rgb)
        # The model head is a bare nn.Linear (raw logits). Softmax so `conf`
        # and `probs` are genuine probabilities; argmax is unaffected.
        if raw.min() < 0 or raw.max() > 1.5 or not np.isclose(raw.sum(), 1.0, atol=1e-3):
            probs = np.exp(raw - raw.max())
            probs = probs / probs.sum()
        else:
            probs = raw
        i = int(probs.argmax())
        return {"class": _CLASSES[i], "conf": float(probs[i]), "source": "model",
                "probs": {c: float(p) for c, p in zip(_CLASSES, probs)}}
    except Exception:
        return _heuristic(rgb)
