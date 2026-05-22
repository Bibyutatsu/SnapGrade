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
    blur_angle_deg: float | None = None  # dominant motion direction (only meaningful when anisotropic)


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


def fft_anisotropy(
    rgb: np.ndarray, bbox: tuple[int, int, int, int] | None = None, return_angle: bool = False
):
    """Ratio of directional vs isotropic high-frequency energy.

    For a defocused blur the high-frequency falloff is roughly isotropic (low
    anisotropy). For camera shake / motion blur, energy is suppressed along
    one direction, producing high anisotropy. Range 0..1.

    With `return_angle=True`, also returns the dominant motion-blur direction
    in degrees (the streak is perpendicular to the peak-energy frequency axis).
    """
    gray = _crop(_to_gray(rgb), bbox).astype(np.float32)
    if gray.size == 0 or min(gray.shape) < 32:
        return (0.0, None) if return_angle else 0.0
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
        return (0.0, None) if return_angle else 0.0
    bin_edges = np.linspace(0, 180, 19)  # 10° bins
    angles = (np.degrees(np.arctan2(dy, dx)) % 180.0)
    idx = np.digitize(angles[mask], bin_edges) - 1
    energies = np.bincount(idx, weights=mag[mask], minlength=len(bin_edges) - 1)
    if energies.sum() == 0:
        return (0.0, None) if return_angle else 0.0
    energies = energies / energies.sum()
    # Anisotropy = max bin energy relative to mean (normalized to 0..1).
    peak = energies.max()
    mean = energies.mean()
    aniso = float(min(1.0, max(0.0, (peak - mean) / (peak + 1e-6))))
    if not return_angle:
        return aniso
    # Peak frequency-energy axis; the motion streak is perpendicular to it.
    peak_bin = int(energies.argmax())
    freq_angle = 0.5 * (bin_edges[peak_bin] + bin_edges[peak_bin + 1])
    motion_angle = (freq_angle + 90.0) % 180.0
    return aniso, float(motion_angle)


def _squash(x: float, k: float) -> float:
    # Soft monotone squashing into 0..1 with knee at k.
    return float(x / (x + k)) if x >= 0 else 0.0


# Resolution the knee constants below were calibrated against. Gradient-energy
# metrics (Tenengrad, Laplacian variance) scale ~1/s² with the working long
# edge s, so a larger analysis image (e.g. --max-edge 3000) would otherwise read
# as uniformly *softer* and shift every verdict. Scaling the knees by (REF/edge)²
# makes the score scale-invariant; it's an exact no-op at the 2000px default.
_REF_LONG_EDGE = 2000.0


def measure(rgb: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> Sharpness:
    lap = laplacian_variance(rgb, bbox)
    ten = tenengrad(rgb, bbox)
    aniso, angle = fft_anisotropy(rgb, bbox, return_angle=True)
    # Knee values calibrated for ~2000px-long-edge analysis images, rescaled to
    # the actual working resolution so --max-edge doesn't drift the score.
    long_edge = float(max(rgb.shape[0], rgb.shape[1])) or _REF_LONG_EDGE
    scale = (_REF_LONG_EDGE / long_edge) ** 2
    score = 0.5 * _squash(lap, 150.0 * scale) + 0.5 * _squash(ten, 600.0 * scale)
    return Sharpness(
        laplacian_var=lap,
        tenengrad=ten,
        fft_anisotropy=aniso,
        score=score,
        blur_angle_deg=angle if aniso > 0.45 else None,
    )
