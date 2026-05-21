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

# Minimum bbox area (fraction of image) for a face to count as a primary
# subject at all. Below this, the largest face is too small to trust even if
# it's the only detected face.
MIN_FACE_AREA_RATIO = 0.0005
# Other faces within this fraction of the largest face's area are co-primary
# (e.g. a couple shot — both faces the same size).
SIMILAR_SIZE_RATIO = 0.55
# When >= this many faces are within SIMILAR_SIZE_RATIO of the largest, the
# scene is treated as a crowd unless an optional model (salient seg / person
# detector) disambiguates one face as foreground.
CROWD_CLUSTER_SIZE = 3


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
    """Fallback when no face is found — find the dominant salient region.

    Prefers Apple Vision's attention-based saliency (ANE-accelerated, much
    sharper bbox); falls back to OpenCV StaticSaliencyFineGrained on
    non-macOS or when the Vision request fails.
    """
    try:
        from . import vision as _vision
        if _vision.is_available():
            res = _vision.attention_saliency(rgb)
            if res is not None:
                x0, y0, x1, y1 = res["bbox"]
                w_box, h_box = max(0, x1 - x0), max(0, y1 - y0)
                if w_box > 0 and h_box > 0:
                    return Subject(
                        bbox=(int(x0), int(y0), int(w_box), int(h_box)),
                        kind="saliency",
                        confidence=float(res["confidence"]),
                    )
    except Exception:
        pass

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


def _bbox_overlap_ratio(face_bbox: tuple[int, int, int, int], region: list[int] | tuple[int, int, int, int]) -> float:
    """Fraction of the face bbox that falls inside the region (x0,y0,x1,y1)."""
    fx, fy, fw, fh = face_bbox
    fx1, fy1 = fx + fw, fy + fh
    rx0, ry0, rx1, ry1 = region
    ix0, iy0 = max(fx, rx0), max(fy, ry0)
    ix1, iy1 = min(fx1, rx1), min(fy1, ry1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    face_area = max(fw * fh, 1)
    return inter / face_area


def _person_bbox_to_xyxy(b: list[int]) -> tuple[int, int, int, int]:
    return int(b[0]), int(b[1]), int(b[2]), int(b[3])


def primary_subjects(
    subjects: list[Subject],
    image_shape: tuple[int, int] | tuple[int, int, int],
    min_area_ratio: float = MIN_FACE_AREA_RATIO,
    similar_size_ratio: float = SIMILAR_SIZE_RATIO,
    crowd_cluster_size: int = CROWD_CLUSTER_SIZE,
    salient_bbox: list[int] | None = None,
    person_bboxes: list[list[int]] | None = None,
) -> list[Subject]:
    """Pick which detected subjects drive downstream rules (sharpness, blink).

    Reasoning:
      - Single face → that's the subject, even if small, as long as it clears
        the absolute minimum size (otherwise the detection is likely noise).
      - Couple / small group of similar-sized faces (2) → both are primary.
      - Crowd (>= CROWD_CLUSTER_SIZE faces of similar size) → no primary
        subject; the scene is treated as a landscape with people in it,
        so we don't run closed-eye verdicts on incidental crowd faces.
      - Mixed sizes (one big face + several small ones) → only the big face
        is primary; the small ones are background.
    """
    h = image_shape[0]
    w = image_shape[1]
    img_area = max(h * w, 1)
    _ = w  # silence "unused" — kept for future signal-extraction code

    # Build a list of "foreground regions" from optional model signals. Any
    # face whose centre falls inside one of these is promoted to primary even
    # if it would otherwise be classified as crowd or too-small.
    #
    # A salient region that covers >25% of the image is treated as scene-level
    # context (e.g. the whole crowd) rather than a single subject, so it's
    # only used when no face was detected — never to promote crowd faces.
    SALIENT_TIGHT_RATIO = 0.25
    fg_regions: list[tuple[int, int, int, int]] = []
    fg_fallback_regions: list[tuple[int, int, int, int]] = []
    if salient_bbox and len(salient_bbox) == 4:
        r = _person_bbox_to_xyxy(salient_bbox)
        area = max(0, r[2] - r[0]) * max(0, r[3] - r[1])
        if area / img_area <= SALIENT_TIGHT_RATIO:
            fg_regions.append(r)
        else:
            fg_fallback_regions.append(r)
    if person_bboxes:
        # Use only the largest person bbox; secondary people are background.
        sized = sorted(
            (_person_bbox_to_xyxy(b) for b in person_bboxes if len(b) >= 4),
            key=lambda r: (r[2] - r[0]) * (r[3] - r[1]),
            reverse=True,
        )
        if sized:
            fg_regions.append(sized[0])

    faces = [s for s in subjects if s.kind == "face"] if subjects else []
    if not faces:
        # No face detector hit. If a model identified a foreground region,
        # synthesise a Subject from the largest such region so downstream code
        # still has something to focus on. Loose salient regions (>40% of the
        # image) are accepted in this fallback path since something is better
        # than nothing when no face is found.
        all_regions = fg_regions + fg_fallback_regions
        if all_regions:
            r = max(all_regions, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            return [Subject(
                bbox=(r[0], r[1], r[2] - r[0], r[3] - r[1]),
                kind="person",
                confidence=0.5,
            )]
        if subjects:
            return [subjects[0]]
        return []

    faces = sorted(faces, key=lambda s: s.bbox[2] * s.bbox[3], reverse=True)
    largest_area = faces[0].bbox[2] * faces[0].bbox[3]

    # When a foreground region is known, faces that fall inside it are the
    # primaries; we don't second-guess via size clustering in that case.
    if fg_regions:
        inside = [
            f for f in faces
            if any(_bbox_overlap_ratio(f.bbox, r) > 0.5 for r in fg_regions)
        ]
        if inside:
            return inside

    if largest_area / img_area < min_area_ratio:
        return []
    cutoff = largest_area * similar_size_ratio
    cluster = [f for f in faces if (f.bbox[2] * f.bbox[3]) >= cutoff]
    if len(cluster) >= crowd_cluster_size:
        return []
    return cluster
