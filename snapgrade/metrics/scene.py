"""Scene classifier (Places365 MobileNetV2, CoreML).

Drop a Places365 CoreML model at ~/.snapgrade/models/places365.mlpackage
(or set SNAPGRADE_SCENE_MODEL) plus a labels file at
~/.snapgrade/models/places365_labels.txt (one label per line).

If either is missing, is_available() returns False and analyze() returns {}.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_MODEL = None
_LABELS: list[str] | None = None
_LOADED = False
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _model_path() -> Path | None:
    p = os.environ.get("SNAPGRADE_SCENE_MODEL")
    if p and Path(p).exists():
        return Path(p)
    default = Path.home() / ".snapgrade" / "models" / "places365.mlpackage"
    return default if default.exists() else None


def _labels_path() -> Path | None:
    p = os.environ.get("SNAPGRADE_SCENE_LABELS")
    if p and Path(p).exists():
        return Path(p)
    default = Path.home() / ".snapgrade" / "models" / "places365_labels.txt"
    return default if default.exists() else None


def is_available() -> bool:
    return _model_path() is not None and _labels_path() is not None


def _clean_label(line: str) -> str:
    """Turn a raw Places365 category line into a human label.

    Places365 ships categories as `/v/village 348` (and two-level entries like
    `/a/apartment_building/outdoor 8`). Strip the leading `/x/` bucket prefix
    and the trailing class index, and turn underscores into spaces.
    """
    token = line.strip().split()[0]          # "/a/apartment_building/outdoor"
    name = token.lstrip("/").split("/", 1)[-1]  # "apartment_building/outdoor"
    return name.replace("/", " ").replace("_", " ").strip()


def _load() -> tuple[Any, list[str]] | None:
    global _MODEL, _LABELS, _LOADED
    if _LOADED:
        return (_MODEL, _LABELS) if _MODEL is not None and _LABELS is not None else None
    _LOADED = True
    mp, lp = _model_path(), _labels_path()
    if not mp or not lp:
        return None
    try:
        from .. import models as _m
        _MODEL = _m.load_coreml(mp)
        _LABELS = [_clean_label(ln) for ln in lp.read_text().splitlines() if ln.strip()]
    except Exception:
        _MODEL, _LABELS = None, None
        return None
    return (_MODEL, _LABELS)


def analyze(rgb: np.ndarray) -> dict[str, Any]:
    loaded = _load()
    if loaded is None:
        return {}
    model, labels = loaded
    try:
        im = Image.fromarray(rgb).resize((224, 224), Image.BILINEAR)
        x = (np.asarray(im, dtype=np.float32) / 255.0 - _MEAN) / _STD
        x = x.transpose(2, 0, 1).astype(np.float32)  # HWC → CHW; CoreML model is NCHW
        out = model.predict({list(model.input_description)[0]: x[None, ...]})
        probs = np.asarray(next(iter(out.values()))).ravel()
        if probs.size != len(labels):
            return {}
        top = probs.argsort()[::-1][:3]
        return {
            "top": [{"label": labels[int(i)], "prob": float(probs[int(i)])} for i in top],
            "primary": labels[int(top[0])],
        }
    except Exception:
        return {}
