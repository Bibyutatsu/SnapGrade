"""Subject detection: faces (OpenCV YuNet) + saliency fallback.

YuNet is OpenCV's full-scene face detector — unlike MediaPipe BlazeFace it
finds small / off-center / multi-scale faces in landscape and group shots,
which is what we need for general photo culling. Returns the largest face as
the primary subject so subject-aware sharpness focuses on the right thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np

_YUNET = None
_YUNET_INPUT_SIZE: tuple[int, int] | None = None


@dataclass(frozen=True)
class Subject:
    bbox: tuple[int, int, int, int]  # x, y, w, h
    kind: str                        # "face" | "saliency"
    confidence: float


def _yunet():
    global _YUNET
    if _YUNET is None:
        from .. import models

        path = models.ensure("yunet")
        _YUNET = cv2.FaceDetectorYN.create(
            str(path),
            "",
            input_size=(320, 320),
            score_threshold=0.7,
            nms_threshold=0.3,
            top_k=50,
        )
    return _YUNET


def detect_faces(rgb: np.ndarray, score_threshold: float = 0.7) -> list[Subject]:
    global _YUNET_INPUT_SIZE
    h, w = rgb.shape[:2]
    detector = _yunet()
    if _YUNET_INPUT_SIZE != (w, h):
        detector.setInputSize((w, h))
        _YUNET_INPUT_SIZE = (w, h)
    detector.setScoreThreshold(score_threshold)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    _, faces = detector.detect(bgr)
    if faces is None:
        return []
    out: list[Subject] = []
    for f in faces:
        x, y, bw, bh = (int(round(v)) for v in f[:4])
        score = float(f[14])
        x = max(0, x)
        y = max(0, y)
        bw = max(0, min(bw, w - x))
        bh = max(0, min(bh, h - y))
        if bw <= 0 or bh <= 0:
            continue
        out.append(Subject(bbox=(x, y, bw, bh), kind="face", confidence=score))
    out.sort(key=lambda s: s.bbox[2] * s.bbox[3], reverse=True)
    return out


def detect_saliency(rgb: np.ndarray) -> Subject | None:
    """Fallback when no face is found — find the dominant salient region."""
    try:
        sal = cv2.saliency.StaticSaliencyFineGrained_create()
    except AttributeError:
        h, w = rgb.shape[:2]
        return Subject(
            bbox=(int(w * 0.2), int(h * 0.2), int(w * 0.6), int(h * 0.6)),
            kind="saliency",
            confidence=0.1,
        )

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, sal_map = sal.computeSaliency(bgr)
    if not ok:
        return None
    sal_u8 = (sal_map * 255).astype(np.uint8)
    _, thresh = cv2.threshold(sal_u8, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    big = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(big)
    if w * h < (rgb.shape[0] * rgb.shape[1]) * 0.01:
        return None
    return Subject(bbox=(x, y, w, h), kind="saliency", confidence=float(np.mean(sal_map)))


def detect_subjects(rgb: np.ndarray) -> list[Subject]:
    faces = detect_faces(rgb)
    if faces:
        return faces
    sal = detect_saliency(rgb)
    return [sal] if sal is not None else []


def primary_bbox(subjects: Iterable[Subject]) -> tuple[int, int, int, int] | None:
    for s in subjects:
        return s.bbox
    return None
