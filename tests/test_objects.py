"""YOLO26 object-detection smoke test against the Crowd bucket.

Skips when the model isn't downloaded so CI without the optional weights stays
green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from snapgrade import decode
from snapgrade.metrics import objects

CROWD = Path("/Users/oindrila/Projects/BlurDetector/Images/Crowd")


@pytest.mark.skipif(not objects.is_available(), reason="YOLO model not downloaded")
def test_yolo_detects_people_in_crowd():
    files = [p for p in CROWD.iterdir() if p.is_file() and decode.is_supported(p)] if CROWD.is_dir() else []
    if not files:
        pytest.skip("Crowd bucket empty")
    with_person = 0
    for p in files:
        rgb = decode.decode(p).rgb
        res = objects.analyze(rgb)
        classes = {d["class"] for d in res.get("detections", [])}
        if "person" in classes:
            with_person += 1
    # Every Crowd image should contain at least one detected person.
    assert with_person == len(files), f"only {with_person}/{len(files)} crowd images had a person"
