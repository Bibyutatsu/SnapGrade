"""Colour metrics: dominant palette + white-balance cast.

Both are cheap, model-free numpy/OpenCV. The palette feeds organizer tokens
(`palette:warm`, `palette:mono`) and the cast surfaces a "colour cast" review
reason when a frame is strongly off-neutral.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass(frozen=True)
class Color:
    dominant: list[list[int]] = field(default_factory=list)  # up to 5 RGB triples
    temperature: str = "neutral"   # warm | cool | neutral
    saturation: str = "neutral"    # mono | muted | vivid
    cast_strength: float = 0.0     # 0..1; how far from grey-world neutral
    cast_hue: str | None = None    # red | green | blue tint when cast is strong


def _dominant_colors(rgb: np.ndarray, k: int = 5) -> list[list[int]]:
    small = cv2.resize(rgb, (64, 64), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    k = min(k, len(np.unique(small, axis=0)))
    if k < 1:
        return []
    _compact, labels, centers = cv2.kmeans(small, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=k)
    order = counts.argsort()[::-1]
    return [[int(c) for c in centers[i]] for i in order]


def measure(rgb: np.ndarray) -> Color:
    dominant = _dominant_colors(rgb)

    means = rgb.reshape(-1, 3).mean(axis=0)  # R, G, B
    r, g, b = (float(x) for x in means)
    grey = (r + g + b) / 3.0 or 1.0

    # Warm/cool from red-vs-blue balance.
    rb = (r - b) / grey
    temperature = "warm" if rb > 0.08 else "cool" if rb < -0.08 else "neutral"

    # Saturation bucket from HSV.
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    s_mean = float(hsv[:, :, 1].mean()) / 255.0
    saturation = "mono" if s_mean < 0.10 else "vivid" if s_mean > 0.45 else "muted"

    # Grey-world cast: deviation of each channel from the grey mean.
    devs = {"red": (r - grey) / grey, "green": (g - grey) / grey, "blue": (b - grey) / grey}
    cast_hue = max(devs, key=devs.get)
    cast_strength = float(min(1.0, max(0.0, devs[cast_hue])))

    return Color(
        dominant=dominant,
        temperature=temperature,
        saturation=saturation,
        cast_strength=cast_strength,
        cast_hue=cast_hue if cast_strength > 0.18 else None,
    )
