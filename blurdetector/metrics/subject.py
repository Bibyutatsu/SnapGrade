"""Subject detection: faces (MediaPipe) with saliency fallback (OpenCV).

Output is a list of subject bounding boxes in pixel coordinates of the input
image. The first box, if any, is treated as the primary subject by the
sharpness pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np

_FACE_DETECTOR = None


@dataclass(frozen=True)
class Subject:
    bbox: tuple[int, int, int, int]  # x, y, w, h
    kind: str                        # "face" | "saliency"
    confidence: float


def _face_detector():
    global _FACE_DETECTOR
    if _FACE_DETECTOR is None:
        import mediapipe as mp

        _FACE_DETECTOR = mp.solutions.face_detection.FaceDetection(
            model_selection=1,  # full-range model; better for non-selfie shots
            min_detection_confidence=0.5,
        )
    return _FACE_DETECTOR


def detect_faces(rgb: np.ndarray) -> list[Subject]:
    h, w = rgb.shape[:2]
    res = _face_detector().process(rgb)
    if not res.detections:
        return []
    out: list[Subject] = []
    for det in res.detections:
        bb = det.location_data.relative_bounding_box
        x = int(round(bb.xmin * w))
        y = int(round(bb.ymin * h))
        bw = int(round(bb.width * w))
        bh = int(round(bb.height * h))
        if bw <= 0 or bh <= 0:
            continue
        score = float(det.score[0]) if det.score else 0.0
        out.append(Subject(bbox=(x, y, bw, bh), kind="face", confidence=score))
    # Largest face first — that's the primary subject in most photos.
    out.sort(key=lambda s: s.bbox[2] * s.bbox[3], reverse=True)
    return out


def detect_saliency(rgb: np.ndarray) -> Subject | None:
    """Fallback when no face is found — find the dominant salient region."""
    try:
        sal = cv2.saliency.StaticSaliencyFineGrained_create()
    except AttributeError:
        # cv2.saliency is in opencv-contrib; if missing, fall back to a simple
        # center-weighted crop covering the middle 60% of the frame.
        h, w = rgb.shape[:2]
        x = int(w * 0.2)
        y = int(h * 0.2)
        return Subject(bbox=(x, y, int(w * 0.6), int(h * 0.6)), kind="saliency", confidence=0.1)

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
