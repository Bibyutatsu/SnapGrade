"""Apple Vision wrapper smoke tests. Skipped when Vision is unavailable."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from snapgrade import decode
from snapgrade.metrics import vision

IMAGES = Path("/Users/oindrila/Projects/BlurDetector/Images")

pytestmark = pytest.mark.skipif(not vision.is_available(), reason="Vision framework unavailable")


def _first(bucket: str) -> Path | None:
    d = IMAGES / bucket
    if not d.is_dir():
        return None
    files = [p for p in sorted(d.iterdir()) if p.is_file() and decode.is_supported(p)]
    return files[0] if files else None


def test_ocr_finds_text_in_scenery():
    p = _first("Scenery with text")
    if p is None:
        pytest.skip("no scenery image")
    rgb = decode.decode(p).rgb
    regions = vision.recognize_text(rgb)
    assert len(regions) >= 1
    assert all("text" in r and "bbox" in r for r in regions)


def test_screenshot_has_more_text_than_photo():
    shot = _first("Screenshots")
    photo = _first("Uncategorized")
    if shot is None or photo is None:
        pytest.skip("missing comparison images")
    n_shot = len(vision.recognize_text(decode.decode(shot).rgb))
    n_photo = len(vision.recognize_text(decode.decode(photo).rgb))
    assert n_shot > n_photo


def test_graceful_on_tiny_image():
    rgb = np.zeros((16, 16, 3), dtype=np.uint8)
    # Must not raise. A blank image yields no text/animals; doc segmentation
    # always returns a candidate, so only assert it's low-confidence or None.
    assert vision.recognize_text(rgb) == []
    assert vision.recognize_animals(rgb) == []
    doc = vision.document_segmentation(rgb)
    assert doc is None or doc["confidence"] < 0.5
