"""Eye openness / blink detection + ARKit blendshape expression.

Strategy: YuNet finds faces at full-scene scale, then we crop each face (with
padding) and feed the crop to MediaPipe FaceLandmarker — which is what
landmarkers are designed for (a close-up of one face). The blendshape outputs
`eyeBlinkLeft` and `eyeBlinkRight` (0=open, 1=fully closed) are the primary
signal; classical EAR is computed from landmarks as a secondary check.

The same blendshape pass is also the source of truth for facial expression:
`mouthSmileLeft/Right` drive `smile_score`, `mouthFrownLeft/Right` plus
`browDownLeft/Right` drive `frown_score`. These feed the burst picker in
`group.py` so portrait bursts prefer open eyes + smiles.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import subject

LEFT_EYE_LMS = (33, 160, 158, 133, 153, 144)
RIGHT_EYE_LMS = (362, 385, 387, 263, 373, 380)

CLOSED_BLEND_THRESHOLD = 0.50
CLOSED_EAR_THRESHOLD = 0.20

_LANDMARKER = None


@dataclass(frozen=True)
class EyeReport:
    faces: int
    ears: tuple[float, ...]
    blinks: tuple[tuple[float, float], ...]
    min_ear: float | None
    max_blink: float | None
    any_closed: bool
    # Per-face expression (parallel to `ears` / `blinks`). Empty when no
    # blendshapes were produced.
    smiles: tuple[float, ...] = ()
    frowns: tuple[float, ...] = ()
    brows_down: tuple[float, ...] = ()
    # Whole-frame aggregates — max across faces; None when no faces.
    max_smile: float | None = None
    max_frown: float | None = None
    max_brow_down: float | None = None


def _landmarker():
    global _LANDMARKER
    if _LANDMARKER is None:
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        from .. import models

        path = models.ensure("face_landmarker")
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
        )
        _LANDMARKER = mp_vision.FaceLandmarker.create_from_options(options)
    return _LANDMARKER


def _ear(pts: np.ndarray) -> float:
    p1, p2, p3, p4, p5, p6 = pts
    horiz = np.linalg.norm(p1 - p4)
    if horiz < 1e-6:
        return 0.0
    v1 = np.linalg.norm(p2 - p6)
    v2 = np.linalg.norm(p3 - p5)
    return float((v1 + v2) / (2.0 * horiz))


_EXPRESSION_KEYS = (
    "eyeBlinkLeft", "eyeBlinkRight",
    "mouthSmileLeft", "mouthSmileRight",
    "mouthFrownLeft", "mouthFrownRight",
    "browDownLeft", "browDownRight",
)


def _expression_scores(blendshapes) -> dict[str, float]:
    """Extract the blendshape coefficients we use for blink / smile / frown."""
    out = {k: 0.0 for k in _EXPRESSION_KEYS}
    for cat in blendshapes:
        if cat.category_name in out:
            out[cat.category_name] = float(cat.score)
    return out


def _blink_scores(blendshapes) -> tuple[float, float]:
    s = _expression_scores(blendshapes)
    return s["eyeBlinkLeft"], s["eyeBlinkRight"]


def _pad_crop(rgb: np.ndarray, bbox: tuple[int, int, int, int], pad: float = 0.4) -> np.ndarray:
    h, w = rgb.shape[:2]
    x, y, bw, bh = bbox
    px = int(bw * pad)
    py = int(bh * pad)
    x0 = max(0, x - px)
    y0 = max(0, y - py)
    x1 = min(w, x + bw + px)
    y1 = min(h, y + bh + py)
    return rgb[y0:y1, x0:x1]


def measure(rgb: np.ndarray, faces: list[subject.Subject] | None = None) -> EyeReport:
    """Run blink detection on each detected face.

    `faces` is optional — when caller already has YuNet results we avoid the
    duplicate face-detection cost.
    """
    import mediapipe as mp

    if faces is None:
        faces = subject.detect_faces(rgb)
    # Only run blink detection on primary subjects — small background/crowd
    # faces routinely false-positive on closed-eyes from MediaPipe at low res.
    faces = subject.primary_subjects(faces or [], rgb.shape)
    if not faces:
        return EyeReport(faces=0, ears=(), blinks=(), min_ear=None, max_blink=None, any_closed=False)

    lm = _landmarker()
    ears: list[float] = []
    blinks: list[tuple[float, float]] = []
    smiles: list[float] = []
    frowns: list[float] = []
    brows_down: list[float] = []
    any_closed = False

    for face in faces:
        crop = _pad_crop(rgb, face.bbox, pad=0.4)
        if crop.size == 0 or min(crop.shape[:2]) < 32:
            continue
        ch, cw = crop.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop))
        res = lm.detect(image)
        if not res.face_landmarks:
            continue
        face_lms = res.face_landmarks[0]
        lms = np.array([(p.x * cw, p.y * ch) for p in face_lms], dtype=np.float32)
        left = _ear(lms[list(LEFT_EYE_LMS)])
        right = _ear(lms[list(RIGHT_EYE_LMS)])
        ears.append(min(left, right))

        if res.face_blendshapes:
            bs = _expression_scores(res.face_blendshapes[0])
        else:
            bs = {k: 0.0 for k in _EXPRESSION_KEYS}
        bl, br = bs["eyeBlinkLeft"], bs["eyeBlinkRight"]
        blinks.append((bl, br))
        smiles.append(max(bs["mouthSmileLeft"], bs["mouthSmileRight"]))
        frowns.append(max(bs["mouthFrownLeft"], bs["mouthFrownRight"]))
        brows_down.append(max(bs["browDownLeft"], bs["browDownRight"]))

        if max(bl, br) >= CLOSED_BLEND_THRESHOLD or min(left, right) < CLOSED_EAR_THRESHOLD:
            any_closed = True

    return EyeReport(
        faces=len(ears),
        ears=tuple(ears),
        blinks=tuple(blinks),
        min_ear=float(min(ears)) if ears else None,
        max_blink=max((max(b) for b in blinks), default=None) if blinks else None,
        any_closed=any_closed,
        smiles=tuple(smiles),
        frowns=tuple(frowns),
        brows_down=tuple(brows_down),
        max_smile=float(max(smiles)) if smiles else None,
        max_frown=float(max(frowns)) if frowns else None,
        max_brow_down=float(max(brows_down)) if brows_down else None,
    )
