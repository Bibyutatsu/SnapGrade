"""Classify an image as screenshot / document / photo.

Replaces the old synthetic-trained `screendoc` CoreML model with signals that
need no download:

  - Apple Vision OCR    → text-area density (screenshots & docs are text-heavy)
  - Vision doc segment. → a high-confidence document quad ⇒ photographed page
  - colour diversity    → screenshots use few flat UI colours

When Vision is unavailable we fall back to the colour-only heuristic that
shipped with screendoc, so non-macOS installs still get a (weaker) answer.

The result dict mirrors the old screendoc shape — `{class, conf, source}` —
so existing consumers (organize.py, api.py) keep working.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

CLASSES = ("screenshot", "document", "photo")

# A non-photo call is only "confident" (actionable) above this.
MIN_CONF = 0.70

# Tuning thresholds.
_DOC_SEG_CONF = 0.70          # document-quad confidence to call it a document
_SCREENSHOT_TEXT_AREA = 0.04  # fraction of frame covered by OCR text
_SCREENSHOT_MAX_COLORS = 256  # quantized unique colours below this = flat UI
_SCREENSHOT_MIN_BLOCKS = 4    # distinct OCR regions that signal UI text density


def is_available() -> bool:
    """Always available — Vision when present, colour heuristic otherwise."""
    return True


def is_confident(result: dict[str, Any]) -> bool:
    return (
        isinstance(result, dict)
        and result.get("class") in ("screenshot", "document")
        and float(result.get("conf", 0.0)) >= MIN_CONF
    )


def _color_diversity(rgb: np.ndarray) -> int:
    small = np.asarray(Image.fromarray(rgb).resize((96, 96), Image.BILINEAR))
    quantized = (small // 16).reshape(-1, 3)
    return len({tuple(p) for p in quantized})


def _text_area_fraction(rgb: np.ndarray, regions: list[dict[str, Any]]) -> float:
    """Sum of OCR box areas / frame area (boxes may overlap; capped at 1.0)."""
    h, w = rgb.shape[:2]
    frame = float(h * w) or 1.0
    area = 0.0
    for r in regions:
        x0, y0, x1, y1 = r["bbox"]
        area += max(0, x1 - x0) * max(0, y1 - y0)
    return min(1.0, area / frame)


def _heuristic(rgb: np.ndarray) -> dict[str, Any]:
    """Colour-only fallback when Vision is unavailable."""
    colors = _color_diversity(rgb)
    small = np.asarray(Image.fromarray(rgb).resize((96, 96), Image.BILINEAR))
    sat = float(np.std(small.astype(np.float32), axis=2).mean())
    if colors < 80:
        return {"class": "screenshot", "conf": 0.55, "source": "heuristic"}
    if sat < 8.0 and small.mean() > 200:
        return {"class": "document", "conf": 0.55, "source": "heuristic"}
    return {"class": "photo", "conf": 0.55, "source": "heuristic"}


def analyze(
    rgb: np.ndarray,
    ocr_regions: list[dict[str, Any]] | None = None,
    has_camera: bool | None = None,
) -> dict[str, Any]:
    """Classify content type.

    `ocr_regions`  — reuse a prior OCR pass instead of re-running it.
    `has_camera`   — whether EXIF carries a camera model. The single strongest
                     screenshot signal: screenshots have no camera. None = unknown.
    """
    try:
        from . import vision
    except Exception:
        vision = None

    if vision is None or not vision.is_available():
        return _heuristic(rgb)

    regions = ocr_regions if ocr_regions is not None else vision.recognize_text(rgb)
    text_area = _text_area_fraction(rgb, regions)
    colors = _color_diversity(rgb)
    doc = vision.document_segmentation(rgb)
    doc_conf = float(doc["confidence"]) if doc else 0.0
    base = {"text_area": text_area, "colors": colors, "source": "vision",
            "has_camera": has_camera}

    # A camera-shot page with a strong document quad and text = document.
    # (No camera ⇒ it's a screen capture, never a photographed document.)
    if has_camera and doc_conf >= _DOC_SEG_CONF and text_area > 0.01:
        return {"class": "document", "conf": doc_conf, **base}

    # No camera EXIF is a strong screenshot signal, but a photo with a text
    # caption also loses its EXIF — and rich natural colour with only a couple
    # of text blocks is the tell-tale of a real photo, not a UI capture. So
    # require a flat UI palette OR many distinct text blocks (a single big
    # caption doesn't count) before calling it a screenshot.
    if has_camera is False:
        flat_palette = colors < _SCREENSHOT_MAX_COLORS
        text_dense = text_area >= _SCREENSHOT_TEXT_AREA and len(regions) >= _SCREENSHOT_MIN_BLOCKS
        if flat_palette or text_dense:
            conf = min(0.99, 0.80 + text_area)
            return {"class": "screenshot", "conf": float(conf), **base}
        return {"class": "photo", "conf": 0.70, **base}

    # Unknown camera status: fall back to text-density + flat-palette test.
    if text_area >= _SCREENSHOT_TEXT_AREA and colors < _SCREENSHOT_MAX_COLORS:
        return {"class": "screenshot", "conf": float(min(0.99, 0.70 + text_area)), **base}

    return {"class": "photo", "conf": 0.80, **base}
