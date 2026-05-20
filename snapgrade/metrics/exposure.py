"""Exposure metrics from a luma histogram."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Exposure:
    mean_luma: float           # 0..255
    clipped_highlight: float   # fraction of pixels at luma >= 250
    clipped_shadow: float      # fraction of pixels at luma <= 5
    dynamic_range: float       # P99 - P1 in luma units
    underexposed: bool
    overexposed: bool


def measure(rgb: np.ndarray) -> Exposure:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    total = gray.size
    mean = float(gray.mean())
    hi = float(np.count_nonzero(gray >= 250) / total)
    lo = float(np.count_nonzero(gray <= 5) / total)
    p1, p99 = np.percentile(gray, [1, 99])
    return Exposure(
        mean_luma=mean,
        clipped_highlight=hi,
        clipped_shadow=lo,
        dynamic_range=float(p99 - p1),
        underexposed=mean < 50 and lo > 0.20,
        overexposed=mean > 210 or hi > 0.15,
    )
