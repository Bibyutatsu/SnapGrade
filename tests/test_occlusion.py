"""Sunglasses / dark-lens occlusion detection + its effect on the verdict."""

import numpy as np

from snapgrade.decide import Thresholds, decide
from snapgrade.metrics.face_expression import (
    LEFT_EYE_LMS,
    RIGHT_EYE_LMS,
    _eye_region_occluded,
)


def _lms_in_rect(x0=40, y0=30, x1=90, y1=45):
    """A landmark array whose eye-group indices span the given rectangle."""
    lms = np.zeros((478, 2), dtype=np.float32)
    idxs = list(LEFT_EYE_LMS + RIGHT_EYE_LMS)
    for i in idxs:
        lms[i] = (65.0, 37.0)
    lms[idxs[0]] = (x0, y0)
    lms[idxs[1]] = (x1, y1)
    return lms


def _crop(fill):
    return np.full((130, 130, 3), fill, dtype=np.uint8)


# --- detector ---------------------------------------------------------------


def test_dark_lens_over_skin_is_occluded():
    crop = _crop((200, 150, 130))  # skin everywhere
    crop[0:54, 30:99] = (10, 10, 12)  # dark lens over the (padded) eye region
    assert _eye_region_occluded(crop, _lms_in_rect()) is True


def test_skin_toned_eyelid_blink_is_not_occluded():
    crop = _crop((190, 150, 135))  # a closed eyelid is skin-toned, all over
    assert _eye_region_occluded(crop, _lms_in_rect()) is False


def test_uniform_low_light_face_is_not_occluded():
    crop = _crop((47, 47, 49))  # dark scene, but cheeks just as dark
    crop[0:54, 30:99] = (43, 43, 45)  # eye region only marginally darker → ratio ~0.92
    assert _eye_region_occluded(crop, _lms_in_rect()) is False


def test_clear_eyeglasses_is_not_occluded():
    crop = _crop((200, 150, 130))
    crop[0:54, 30:99] = (150, 140, 150)  # bright, mildly desaturated lens
    assert _eye_region_occluded(crop, _lms_in_rect()) is False


# --- decision layer ---------------------------------------------------------


def _sharp_keeper(**eyes):
    return {
        "sharpness": {"score": 0.85, "laplacian_var": 400.0, "fft_anisotropy": 0.1},
        "exposure": {"mean_luma": 128.0, "dynamic_range": 180.0},
        "eyes": {"faces": 1, "any_closed": True, **eyes},
        "composition": {"horizon_tilt_deg": 0.2, "thirds_offset": 0.1},
    }


def test_sunglasses_face_not_rejected():
    m = _sharp_keeper(closed_count=1, occluded_count=1)
    v = decide(m, Thresholds())
    assert v.verdict != "reject"
    assert "eyes closed" not in v.reasons


def test_real_blink_still_rejected():
    m = _sharp_keeper(closed_count=1, occluded_count=0)
    v = decide(m, Thresholds())
    assert v.verdict == "reject"
    assert "eyes closed" in v.reasons


def test_group_all_occluded_not_rejected():
    m = _sharp_keeper(faces=3, closed_count=2, occluded_count=2)
    v = decide(m, Thresholds())
    assert v.verdict != "reject"


def test_missing_occluded_count_is_backward_compatible():
    m = _sharp_keeper(closed_count=1)  # no occluded_count key
    v = decide(m, Thresholds())
    assert v.verdict == "reject"
    assert "eyes closed" in v.reasons
