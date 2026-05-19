"""Eye openness / blink detection via MediaPipe FaceMesh + Eye Aspect Ratio.

Returns a list of per-face EAR values plus an aggregate `min_ear` and a flag
`any_closed` triggered when any detected face is below the closed threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Landmark indices on the MediaPipe FaceMesh 468-point topology.
# The 6 points used by the classic Soukupová–Čech EAR formulation:
#   horizontal: p1, p4   vertical: (p2,p6) and (p3,p5)
LEFT_EYE_LMS = (33, 160, 158, 133, 153, 144)
RIGHT_EYE_LMS = (362, 385, 387, 263, 373, 380)

CLOSED_THRESHOLD = 0.20  # Below this EAR, the eye is treated as closed.

_FACEMESH = None


@dataclass(frozen=True)
class EyeReport:
    faces: int
    ears: tuple[float, ...]     # per-face min(left, right) EAR
    min_ear: float | None
    any_closed: bool


def _facemesh():
    global _FACEMESH
    if _FACEMESH is None:
        import mediapipe as mp

        _FACEMESH = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=10,
            refine_landmarks=False,
            min_detection_confidence=0.5,
        )
    return _FACEMESH


def _ear(pts: np.ndarray) -> float:
    # pts shape: (6, 2) — order: p1..p6
    p1, p2, p3, p4, p5, p6 = pts
    horiz = np.linalg.norm(p1 - p4)
    if horiz < 1e-6:
        return 0.0
    v1 = np.linalg.norm(p2 - p6)
    v2 = np.linalg.norm(p3 - p5)
    return float((v1 + v2) / (2.0 * horiz))


def measure(rgb: np.ndarray) -> EyeReport:
    h, w = rgb.shape[:2]
    res = _facemesh().process(rgb)
    if not res.multi_face_landmarks:
        return EyeReport(faces=0, ears=(), min_ear=None, any_closed=False)

    per_face: list[float] = []
    for face in res.multi_face_landmarks:
        lms = np.array([(lm.x * w, lm.y * h) for lm in face.landmark], dtype=np.float32)
        left = _ear(lms[list(LEFT_EYE_LMS)])
        right = _ear(lms[list(RIGHT_EYE_LMS)])
        per_face.append(min(left, right))

    min_ear = float(min(per_face)) if per_face else None
    return EyeReport(
        faces=len(per_face),
        ears=tuple(per_face),
        min_ear=min_ear,
        any_closed=any(e < CLOSED_THRESHOLD for e in per_face),
    )
