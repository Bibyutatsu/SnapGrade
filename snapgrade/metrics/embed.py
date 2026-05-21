"""MobileCLIP-S0 image embedding.

Lazy-loaded CoreML image tower. Heavy import (`coremltools`) lives inside the
loader so the rest of the package can import without it. Returns a 512-d L2-
normalized float32 vector. Returns None when the model is missing — caller
treats that as "semantic search disabled".

Override via SNAPGRADE_MOBILECLIP_IMAGE_MODEL; otherwise auto-downloaded via
`snapgrade.models.ensure("mobileclip_image")`.

Output convention:
- model name:  "mobileclip_s0"
- dim:         512
- normalized:  yes (cosine == dot product)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

MODEL_NAME = "mobileclip_s0"
DIM = 512
_INPUT_SIZE = 256  # MobileCLIP-S0 takes 256×256 (not 224 like ViT-B/16)

_MODEL = None
_LOADED = False

# Apple MobileCLIP-S0's official preprocess is just Resize + CenterCrop + ToTensor
# — no mean/std subtraction. Input range is [0, 1]. (Confirmed by inspecting
# mobileclip.create_model_and_transforms.)


def _load() -> object | None:
    global _MODEL, _LOADED
    if _LOADED:
        return _MODEL
    _LOADED = True
    path = os.environ.get("SNAPGRADE_MOBILECLIP_IMAGE_MODEL")
    if not path:
        try:
            from .. import models
            path = str(models.ensure("mobileclip_image"))
        except Exception:
            default = Path.home() / ".snapgrade" / "models" / "mobileclip_s0_image.mlpackage"
            if default.exists():
                path = str(default)
    if not path or not Path(path).exists():
        return None
    try:
        from .. import models as _m
        _MODEL = _m.load_coreml(path)
    except Exception:
        _MODEL = None
    return _MODEL


def _preprocess(rgb: np.ndarray) -> np.ndarray:
    im = Image.fromarray(rgb).resize((_INPUT_SIZE, _INPUT_SIZE), Image.BILINEAR)
    arr = np.asarray(im, dtype=np.float32) / 255.0
    return arr.transpose(2, 0, 1).astype(np.float32)


def is_available() -> bool:
    return _load() is not None


def compute(rgb: np.ndarray) -> np.ndarray | None:
    """Return a 512-d L2-normalized float32 vector, or None if model is absent."""
    model = _load()
    if model is None:
        return None
    try:
        x = _preprocess(rgb)
        out = model.predict({list(model.input_description)[0]: x[None, ...]})  # type: ignore[attr-defined]
        vec = np.asarray(next(iter(out.values())), dtype=np.float32).ravel()
        if vec.size != DIM:
            return None
        n = float(np.linalg.norm(vec))
        if n < 1e-6:
            return None
        return (vec / n).astype(np.float32)
    except Exception:
        return None
