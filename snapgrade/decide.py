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
    # A frame is only rejected for closed eyes when the sole subject blinked, or
    # at least this fraction of the (primary) faces are closed — so one person
    # blinking in a group portrait no longer kills the frame.
    closed_eyes_min_ratio: float = 0.5
    # Continuous eye-openness scoring band: EAR ear_closed..ear_open maps to 0..1.
    # The hard closed-eye *gate* (any_closed) is owned by the analyzer
    # (face_expression.CLOSED_EAR_THRESHOLD); these are the decision layer's
    # scoring bounds, kept here so they're tunable alongside the other knobs.
    ear_closed: float = 0.20
    ear_open: float = 0.35
    # Faces confidently wearing dark sunglasses are flagged by the analyzer as
    # occluded; we subtract them from the closed-eye count so a lens is never
    # mistaken for a blink. Set False to ignore the signal.
    discount_occluded_eyes: bool = True

    # Composition
    horizon_warn_deg: float = 3.0  # surfaces a warning, never auto-rejects

    # Depth
    accept_focus_on_background: bool = False  # don't reject foreground-soft frames

    # Subject-sharpness overrides (face subjects only). soft_face_lap_max is tuned
    # for a face whose long edge is ~SOFT_FACE_REF_PX of the decoded long edge;
    # smaller faces carry less high-frequency detail, so the effective threshold
    # scales down with the face's rendered size (see _soft_face_threshold).
    soft_face_lap_max: float = 50.0  # laplacian var below this on a reference face = soft
    motion_blur_anisotropy: float = 0.45  # FFT anisotropy above this = directional (motion) blur

    # Weights for the combined "quality" score used to assign stars.
    w_sharpness: float = 0.50
    w_exposure: float = 0.18
    w_eyes: float = 0.14
    w_composition: float = 0.08
    w_aesthetic: float = 0.10


@dataclass
class Verdict:
    verdict: str  # keeper | review | reject
    stars: int  # 0..5 (0 = reject, no rating)
    label: str | None  # color label
    reasons: list[str] = field(default_factory=list)
    # Informational flags that did NOT drive the verdict (horizon tilt, colour
    # cast). Kept separate from `reasons` so the UI can style them as advisories
    # rather than as problems that explain a downgrade.
    warnings: list[str] = field(default_factory=list)
    score: float = 0.0  # 0..1 combined quality


def _exposure_score(exposure: dict[str, Any]) -> float:
    if exposure.get("overexposed") or exposure.get("underexposed"):
        return 0.2
    # Reward mid-luma frames with healthy dynamic range.
    mean = exposure.get("mean_luma", 128.0)
    dr = exposure.get("dynamic_range", 0.0)
    mid_bonus = 1.0 - abs(mean - 128.0) / 128.0
    dr_bonus = min(1.0, dr / 200.0)
    return float(0.6 * mid_bonus + 0.4 * dr_bonus)


def _eyes_score(
    eyes: dict[str, Any], ear_closed: float = 0.20, ear_open: float = 0.35
) -> float | None:
    """Eye-openness in 0..1, or None when there's no usable signal.

    Returning None (no faces, or landmarks failed so min_ear is missing) lets the
    caller drop the term and renormalize — previously these silently scored 0.5,
    biasing the distribution between libraries with and without face landmarks.
    """
    if eyes.get("faces", 0) == 0:
        return None
    if eyes.get("any_closed"):
        n_closed = eyes.get("closed_count")
        n_occluded = eyes.get("occluded_count", 0) or 0
        # A sunglasses-only "closed" frame shouldn't zero the eye term; fall
        # through to EAR-band scoring. Genuine blinks still score 0.
        if n_closed is None or max(0, n_closed - n_occluded) > 0:
            return 0.0
    min_ear = eyes.get("min_ear")
    if min_ear is None:
        return None
    span = max(ear_open - ear_closed, 1e-6)
    return max(0.0, min(1.0, (min_ear - ear_closed) / span))


def _composition_score_opt(comp: dict[str, Any]) -> float | None:
    """Composition score, or None when no horizon/thirds data exists."""
    if comp.get("horizon_tilt_deg") is None and comp.get("thirds_offset") is None:
        return None
    return _composition_score(comp)


# A face whose long edge is this fraction of the decoded long edge is the
# reference size soft_face_lap_max was tuned against.
SOFT_FACE_REF_FRAC = 0.35


def _soft_face_threshold(base: float, metrics: dict[str, Any]) -> float:
    """Scale soft_face_lap_max by the face's rendered size.

    Laplacian variance falls with the pixel size of the region, so comparing a
    small face in a 2000px decode and a large face in a 4000px decode against the
    same constant is wrong. Scale the threshold by (face_long / decoded_long)
    relative to the reference fraction, clamped to a sane band.
    """
    decoded = metrics.get("decoded_size") or []
    faces = [
        s for s in (metrics.get("subjects") or []) if s.get("kind") == "face" and s.get("bbox")
    ]
    if len(decoded) != 2 or not faces:
        return base
    decoded_long = max(decoded) or 1
    # Largest face drives subject-aware sharpness (pipeline picks the biggest).
    bw, bh = max((s["bbox"][2], s["bbox"][3]) for s in faces)
    face_long = max(bw, bh)
    frac = face_long / decoded_long
    scale = max(0.4, min(1.5, frac / SOFT_FACE_REF_FRAC))
    return base * scale


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
    eyes_score = _eyes_score(eyes, t.ear_closed, t.ear_open)
    comp_score = _composition_score_opt(comp)
    aesthetic_score = metrics.get("aesthetic_score")
    aesthetic_source = metrics.get("aesthetic_source")
    if aesthetic_score is not None and aesthetic_source == "topiq":
        # Normalize TopIQ's typical [0.35, 0.75] range to [0.0, 1.0] so it
        # contributes fairly to the combined score and stars.
        aesthetic_score = max(0.0, min(1.0, (aesthetic_score - 0.35) / 0.40))

    # Weighted score over only the terms that have a real signal — missing
    # aesthetic / eyes / composition drop out and the remaining weights are
    # renormalized, so the same photo scores the same regardless of which
    # optional models ran.
    terms = [
        (t.w_sharpness, sharp_score),
        (t.w_exposure, exposure_score),
        (t.w_eyes, eyes_score),
        (t.w_composition, comp_score),
        (t.w_aesthetic, aesthetic_score),
    ]
    present = [(w, v) for w, v in terms if v is not None]
    total_w = sum(w for w, _ in present) or 1.0
    score = sum(w * v for w, v in present) / total_w

    reasons: list[str] = []
    warnings: list[str] = []
    verdict = "keeper"

    # When a real face is the subject and its sharpness is poor, that's a
    # reject even if Tenengrad on hair/fabric edges keeps the score in the
    # review band. We only apply this override for face-subjects — for
    # saliency fallback the bbox is too unreliable.
    face_subject = any(s.get("kind") == "face" for s in (metrics.get("subjects") or []))
    ss = subject_sharp or sharp
    lap_val = ss.get("laplacian_var", 0.0)
    aniso = ss.get("fft_anisotropy", 0.0)
    blur_angle = ss.get("blur_angle_deg")
    soft_face = (
        face_subject
        and subject_sharp is not None
        and lap_val < _soft_face_threshold(t.soft_face_lap_max, metrics)
    )
    if aniso > t.motion_blur_anisotropy:
        blur_kind = f"motion blur (~{blur_angle:.0f}°)" if blur_angle is not None else "motion blur"
    else:
        blur_kind = "out of focus"

    # Depth-aware focus miss: foreground subject soft while the background is
    # sharp. This is invisible to a plain sharpness score (the frame *has* sharp
    # edges, just on the wrong plane), so surface it as its own reject reason.
    depth = metrics.get("depth") or {}
    focus_on_background = bool(depth.get("focus_on_background"))

    if sharp_score < t.sharp_reject or (soft_face and sharp_score < t.sharp_keeper):
        verdict = "reject"
        reasons.append(blur_kind)
    elif focus_on_background and not t.accept_focus_on_background:
        verdict = "reject"
        reasons.append("subject out of focus (background sharp)")
    elif sharp_score < t.sharp_keeper:
        verdict = "review"
        reasons.append("slightly soft")

    # Closed eyes reject only when the lone subject blinked, or a meaningful
    # share of the primary faces are closed — not for one blink in a group.
    if t.reject_closed_eyes and eyes.get("any_closed"):
        n_faces = eyes.get("faces", 0) or 0
        n_closed = eyes.get("closed_count")
        n_occluded = eyes.get("occluded_count", 0) or 0  # missing key → 0 → old behaviour
        if n_closed is None:  # pre-closed_count data: fall back to old behaviour
            reject_eyes = True
            effective_closed = None
        else:
            effective_closed = n_closed - n_occluded if t.discount_occluded_eyes else n_closed
            effective_closed = max(0, effective_closed)
            if effective_closed == 0:  # every closed face is a dark lens — not a blink
                reject_eyes = False
            else:
                ratio = effective_closed / n_faces if n_faces else 1.0
                reject_eyes = n_faces <= 1 or ratio >= t.closed_eyes_min_ratio
        if reject_eyes:
            verdict = "reject"
            shown = effective_closed if effective_closed is not None else n_closed
            reasons.append("eyes closed" if n_faces <= 1 else f"eyes closed ({shown}/{n_faces})")
        elif effective_closed:
            warnings.append(f"{effective_closed} of {n_faces} subjects blinking")

    if exposure.get("overexposed") and not t.accept_overexposed:
        if verdict == "keeper":
            verdict = "review"
        reasons.append("overexposed / clipped highlights")
    if exposure.get("underexposed") and not t.accept_underexposed:
        if verdict == "keeper":
            verdict = "review"
        reasons.append("underexposed")

    # Horizon tilt and colour cast are advisories, not verdict drivers — they go
    # to `warnings` so the UI doesn't render them as problems on a keeper.
    tilt = comp.get("horizon_tilt_deg")
    if tilt is not None and abs(tilt) > t.horizon_warn_deg:
        warnings.append(f"horizon tilt {tilt:+.1f}°")

    color = metrics.get("color") or {}
    if color.get("cast_hue") and color.get("cast_strength", 0.0) > 0.25:
        warnings.append(f"{color['cast_hue']} colour cast")

    # Bin the continuous score into stars, then clamp to the verdict band so the
    # two signals can never disagree (no 1★ keeper, no starred reject).
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

    if verdict == "reject":
        stars = 0  # rejects carry no rating
    elif verdict == "keeper":
        stars = max(stars, 3)  # a keeper is at least 3★
    else:  # review
        stars = max(2, min(stars, 4))

    label = {"keeper": "green", "review": "yellow", "reject": "red"}[verdict]

    return Verdict(
        verdict=verdict, stars=stars, label=label, reasons=reasons, warnings=warnings, score=score
    )
