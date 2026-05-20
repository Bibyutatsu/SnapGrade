"""Sharpness / focus metrics.

We compute three complementary signals:
  * Variance of Laplacian — fast, but noise-sensitive.
  * Tenengrad — Sobel gradient energy, robust to noise.
  * FFT directional energy — separates camera shake from defocus.

All operate on a grayscale image. Optional ROI restricts the computation to
a bounding box (used by the subject-aware sharpness path).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class Sharpness:
    laplacian_var: float
    tenengrad: float
    fft_anisotropy: float  # 0 = isotropic blur (defocus), 1 = strongly directional (motion)
    score: float           # combined 0..1 sharpness (higher = sharper)


def _to_gray(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)


def _crop(arr: np.ndarray, bbox: tuple[int, int, int, int] | None) -> np.ndarray:
    if bbox is None:
        return arr
    x, y, w, h = bbox
    H, W = arr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return arr
    return arr[y0:y1, x0:x1]


def laplacian_variance(rgb: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> float:
    gray = _crop(_to_gray(rgb), bbox)
    if gray.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def tenengrad(rgb: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> float:
    gray = _crop(_to_gray(rgb), bbox)
    if gray.size == 0:
        return 0.0
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.mean(gx * gx + gy * gy))


def fft_anisotropy(rgb: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> float:
    """Ratio of directional vs isotropic high-frequency energy.

    For a defocused blur the high-frequency falloff is roughly isotropic (low
    anisotropy). For camera shake / motion blur, energy is suppressed along
    one direction, producing high anisotropy. Range 0..1.
    """
    gray = _crop(_to_gray(rgb), bbox).astype(np.float32)
    if gray.size == 0 or min(gray.shape) < 32:
        return 0.0
    gray = gray - gray.mean()
    # Hann window to reduce edge artifacts
    h, w = gray.shape
    hann = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    f = np.fft.fftshift(np.fft.fft2(gray * hann))
    mag = np.abs(f)
    # Sum energy in angular bins, ignore the very-low-frequency core.
    cy, cx = h // 2, w // 2
    yy, xx = np.indices(mag.shape)
    dy, dx = yy - cy, xx - cx
    r = np.hypot(dy, dx)
    inner = max(8, min(h, w) // 16)
    outer = min(h, w) // 2
    mask = (r > inner) & (r < outer)
    if not np.any(mask):
        return 0.0
    angles = (np.degrees(np.arctan2(dy, dx)) % 180.0)
    bins = np.linspace(0, 180, 19)  # 10° bins
    idx = np.digitize(angles[mask], bins) - 1
    energies = np.bincount(idx, weights=mag[mask], minlength=len(bins) - 1)
    if energies.sum() == 0:
        return 0.0
    energies = energies / energies.sum()
    # Anisotropy = max bin energy relative to mean (normalized to 0..1).
    peak = energies.max()
    mean = energies.mean()
    return float(min(1.0, max(0.0, (peak - mean) / (peak + 1e-6))))


def _squash(x: float, k: float) -> float:
    # Soft monotone squashing into 0..1 with knee at k.
    return float(x / (x + k)) if x >= 0 else 0.0


def measure(rgb: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> Sharpness:
    lap = laplacian_variance(rgb, bbox)
    ten = tenengrad(rgb, bbox)
    aniso = fft_anisotropy(rgb, bbox)
    # Knee values calibrated for ~2000px-long-edge analysis images. The user
    # can re-tune via the settings UI; these are sensible defaults.
    score = 0.5 * _squash(lap, 150.0) + 0.5 * _squash(ten, 600.0)
    return Sharpness(
        laplacian_var=lap,
        tenengrad=ten,
        fft_anisotropy=aniso,
        score=score,
    )
