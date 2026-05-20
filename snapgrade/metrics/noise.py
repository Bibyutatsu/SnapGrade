"""Fast noise sigma estimation (Immerkær 1996).

The trick: convolve with a kernel that's zero-mean on smooth regions and
isolates noise. Median-absolute-deviation-style scaling gives σ directly.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

_KERNEL = np.array(
    [[1, -2, 1],
     [-2, 4, -2],
     [1, -2, 1]],
    dtype=np.float32,
)


def estimate_sigma(rgb: np.ndarray) -> float:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    h, w = gray.shape
    if h < 3 or w < 3:
        return 0.0
    conv = cv2.filter2D(gray, cv2.CV_32F, _KERNEL)
    sigma = float(np.sum(np.abs(conv))) * math.sqrt(0.5 * math.pi) / (6.0 * (w - 2) * (h - 2))
    return sigma
