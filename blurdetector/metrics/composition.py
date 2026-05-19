"""Composition hints: horizon tilt + rule-of-thirds offset of the primary subject."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Composition:
    horizon_tilt_deg: float | None   # signed; None if no dominant horizontal line
    thirds_offset: float | None      # 0=on a thirds intersection, 1=far away; None if no subject


def horizon_tilt(rgb: np.ndarray) -> float | None:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 160, apertureSize=3)
    h = gray.shape[0]
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 360,
        threshold=120,
        minLineLength=int(0.4 * gray.shape[1]),
        maxLineGap=20,
    )
    if lines is None:
        return None
    # Keep only near-horizontal lines (|angle| < 20°) and average their angles
    # weighted by length, so the dominant landscape horizon wins.
    angles: list[float] = []
    weights: list[float] = []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = x2 - x1, y2 - y1
        if dx == 0:
            continue
        ang = np.degrees(np.arctan2(dy, dx))
        if abs(ang) > 20:
            continue
        # ignore lines too close to top/bottom edges (likely frame artifacts)
        midy = 0.5 * (y1 + y2)
        if midy < 0.1 * h or midy > 0.9 * h:
            continue
        length = float(np.hypot(dx, dy))
        angles.append(float(ang))
        weights.append(length)
    if not angles:
        return None
    w = np.array(weights)
    a = np.array(angles)
    return float(np.sum(a * w) / np.sum(w))


def thirds_offset(rgb_shape: tuple[int, int], bbox: tuple[int, int, int, int] | None) -> float | None:
    if bbox is None:
        return None
    h, w = rgb_shape[:2]
    cx = bbox[0] + bbox[2] / 2
    cy = bbox[1] + bbox[3] / 2
    targets = [(w / 3, h / 3), (2 * w / 3, h / 3), (w / 3, 2 * h / 3), (2 * w / 3, 2 * h / 3)]
    diag = float(np.hypot(w, h))
    best = min(np.hypot(cx - tx, cy - ty) for tx, ty in targets)
    return float(best / (0.5 * diag))


def measure(rgb: np.ndarray, primary_bbox: tuple[int, int, int, int] | None) -> Composition:
    return Composition(
        horizon_tilt_deg=horizon_tilt(rgb),
        thirds_offset=thirds_offset(rgb.shape, primary_bbox),
    )
