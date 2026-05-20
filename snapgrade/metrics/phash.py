"""Perceptual hashes for burst / duplicate grouping."""

from __future__ import annotations

from dataclasses import dataclass

import imagehash
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class HashPair:
    phash: str  # 64-bit hex
    dhash: str  # 64-bit hex


def compute(rgb: np.ndarray) -> HashPair:
    im = Image.fromarray(rgb)
    return HashPair(
        phash=str(imagehash.phash(im, hash_size=8)),
        dhash=str(imagehash.dhash(im, hash_size=8)),
    )


def hamming(a_hex: str, b_hex: str) -> int:
    a = int(a_hex, 16)
    b = int(b_hex, 16)
    return (a ^ b).bit_count()
