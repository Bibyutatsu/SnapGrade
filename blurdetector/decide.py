"""Decision engine: metrics + thresholds → verdict + stars + reasons.

The thresholds live here as a dataclass so the UI can serialize / modify them
without touching this logic. Stars are computed on a continuous score and then
binned, so threshold tweaks produce monotone changes (no flip-flops).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Thresholds:
    # Sharpness — measured on the subject if available, else global.
    sharp_keeper: float = 0.55  # >= → keeper-quality sharpness
    sharp_reject: float = 0.30  # < → reject

    # Exposure
    accept_overexposed: bool = False
    accept_underexposed: bool = False

    # Eyes
    reject_closed_eyes: bool = True

    # Composition
    horizon_warn_deg: float = 3.0  # surfaces a warning, never auto-rejects

    # Weights for the combined "quality" score used to assign stars.
    w_sharpness: float = 0.50
    w_exposure: float = 0.18
    w_eyes: float = 0.14
    w_composition: float = 0.08
    w_aesthetic: float = 0.10


@dataclass
class Verdict:
    verdict: str            # keeper | review | reject
    stars: int              # 1..5
    label: str | None       # color label
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0      # 0..1 combined quality


def _exposure_score(exposure: dict[str, Any]) -> float:
    if exposure.get("overexposed") or exposure.get("underexposed"):
        return 0.2
    # Reward mid-luma frames with healthy dynamic range.
    mean = exposure.get("mean_luma", 128.0)
    dr = exposure.get("dynamic_range", 0.0)
    mid_bonus = 1.0 - abs(mean - 128.0) / 128.0
    dr_bonus = min(1.0, dr / 200.0)
    return float(0.6 * mid_bonus + 0.4 * dr_bonus)


def _eyes_score(eyes: dict[str, Any]) -> float:
    if eyes.get("faces", 0) == 0:
        return 1.0  # no faces → eyes can't penalize
    if eyes.get("any_closed"):
        return 0.0
    min_ear = eyes.get("min_ear")
    if min_ear is None:
        return 0.5
    # Map EAR 0.20..0.35 → 0..1
    return max(0.0, min(1.0, (min_ear - 0.20) / 0.15))


def _composition_score(comp: dict[str, Any]) -> float:
    tilt = comp.get("horizon_tilt_deg")
    offset = comp.get("thirds_offset")
    parts: list[float] = []
    if tilt is not None:
        parts.append(max(0.0, 1.0 - abs(tilt) / 10.0))
    if offset is not None:
        parts.append(max(0.0, 1.0 - offset))
    if not parts:
        return 0.5
    return float(sum(parts) / len(parts))


def decide(metrics: dict[str, Any], t: Thresholds | None = None) -> Verdict:
    t = t or Thresholds()
    sharp = metrics.get("sharpness", {})
    subject_sharp = metrics.get("subject_sharpness")
    exposure = metrics.get("exposure", {})
    eyes = metrics.get("eyes", {})
    comp = metrics.get("composition", {})

    sharp_score = (subject_sharp or sharp).get("score", 0.0)
    exposure_score = _exposure_score(exposure)
    eyes_score = _eyes_score(eyes)
    comp_score = _composition_score(comp)

    aesthetic_score = metrics.get("aesthetic_score")
    score = (
        t.w_sharpness * sharp_score
        + t.w_exposure * exposure_score
        + t.w_eyes * eyes_score
        + t.w_composition * comp_score
        + t.w_aesthetic * (aesthetic_score if aesthetic_score is not None else 0.5)
    )

    reasons: list[str] = []
    verdict = "keeper"

    # When a real face is the subject and its sharpness is poor, that's a
    # reject even if Tenengrad on hair/fabric edges keeps the score in the
    # review band. We only apply this override for face-subjects — for
    # saliency fallback the bbox is too unreliable.
    face_subject = any(s.get("kind") == "face" for s in (metrics.get("subjects") or []))
    ss = subject_sharp or sharp
    lap_val = ss.get("laplacian_var", 0.0)
    aniso = ss.get("fft_anisotropy", 0.0)
    soft_face = face_subject and subject_sharp is not None and lap_val < 50.0
    blur_kind = "motion blur" if aniso > 0.45 else "out of focus"

    if sharp_score < t.sharp_reject or (soft_face and sharp_score < t.sharp_keeper):
        verdict = "reject"
        reasons.append(blur_kind)
    elif sharp_score < t.sharp_keeper:
        verdict = "review"
        reasons.append("slightly soft")

    if t.reject_closed_eyes and eyes.get("any_closed"):
        verdict = "reject"
        reasons.append("eyes closed")

    if exposure.get("overexposed") and not t.accept_overexposed:
        if verdict == "keeper":
            verdict = "review"
        reasons.append("overexposed / clipped highlights")
    if exposure.get("underexposed") and not t.accept_underexposed:
        if verdict == "keeper":
            verdict = "review"
        reasons.append("underexposed")

    tilt = comp.get("horizon_tilt_deg")
    if tilt is not None and abs(tilt) > t.horizon_warn_deg:
        reasons.append(f"horizon tilt {tilt:+.1f}°")

    # Bin the continuous score into 1..5 stars (regardless of verdict).
    if score >= 0.80:
        stars = 5
    elif score >= 0.65:
        stars = 4
    elif score >= 0.50:
        stars = 3
    elif score >= 0.35:
        stars = 2
    else:
        stars = 1

    label = {"keeper": "green", "review": "yellow", "reject": "red"}[verdict]

    return Verdict(verdict=verdict, stars=stars, label=label, reasons=reasons, score=score)
