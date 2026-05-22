"""Decision-engine invariants (Phase 4 correctness fixes)."""

from snapgrade.decide import Thresholds, decide


def _sharp_keeper_metrics(**extra):
    m = {
        "sharpness": {"score": 0.85, "laplacian_var": 400.0, "fft_anisotropy": 0.1},
        "exposure": {"mean_luma": 128.0, "dynamic_range": 180.0},
        "eyes": {"faces": 0},
        "composition": {"horizon_tilt_deg": 0.2, "thirds_offset": 0.1},
    }
    m.update(extra)
    return m


def test_missing_aesthetic_does_not_shift_verdict():
    """A frame scored with vs without aesthetic should land on the same verdict;
    the missing term is renormalized, not silently set to 0.5."""
    with_a = _sharp_keeper_metrics(aesthetic_score=0.9)
    without_a = _sharp_keeper_metrics()
    assert decide(with_a).verdict == decide(without_a).verdict == "keeper"
    # Without aesthetic the score must not be dragged toward 0.5 by a phantom term.
    assert decide(without_a).score >= 0.7


def test_missing_min_ear_term_dropped_not_half():
    """faces>0 but no min_ear (landmarks failed) should drop the eyes term, not
    award a free 0.5."""
    base = _sharp_keeper_metrics()
    base["eyes"] = {"faces": 1, "any_closed": False, "min_ear": None}
    # Score should match the no-faces case (eyes term simply absent), not be pulled down.
    no_eyes = decide(_sharp_keeper_metrics()).score
    assert abs(decide(base).score - no_eyes) < 1e-6


def test_group_shot_one_blink_not_rejected():
    m = _sharp_keeper_metrics()
    m["eyes"] = {"faces": 4, "any_closed": True, "closed_count": 1, "min_ear": 0.1}
    v = decide(m)
    assert v.verdict != "reject"
    assert any("blinking" in w for w in v.warnings)


def test_sole_subject_blink_rejected():
    m = _sharp_keeper_metrics()
    m["eyes"] = {"faces": 1, "any_closed": True, "closed_count": 1, "min_ear": 0.1}
    assert decide(m).verdict == "reject"


def test_focus_on_background_override():
    m = _sharp_keeper_metrics(depth={"focus_on_background": True})
    assert decide(m).verdict == "reject"
    assert decide(m, Thresholds(accept_focus_on_background=True)).verdict == "keeper"


def test_horizon_tilt_is_warning_not_reason():
    m = _sharp_keeper_metrics()
    m["composition"] = {"horizon_tilt_deg": 7.0, "thirds_offset": 0.1}
    v = decide(m)
    assert v.verdict == "keeper"
    assert any("horizon" in w for w in v.warnings)
    assert not any("horizon" in r for r in v.reasons)


def test_no_verdict_star_dissonance():
    # Reject → 0 stars.
    bad = {
        "sharpness": {"score": 0.05, "laplacian_var": 5.0, "fft_anisotropy": 0.1},
        "exposure": {"mean_luma": 128.0, "dynamic_range": 180.0},
        "eyes": {"faces": 0},
        "composition": {},
    }
    rv = decide(bad)
    assert rv.verdict == "reject" and rv.stars == 0
    # Keeper → at least 3 stars.
    kv = decide(_sharp_keeper_metrics())
    assert kv.verdict == "keeper" and kv.stars >= 3


def test_soft_face_threshold_scales_with_face_size():
    # A small face with the same laplacian variance should be judged against a
    # lower threshold (so it's less likely to be flagged soft) than a large one.
    metrics = {
        "sharpness": {"score": 0.45, "laplacian_var": 40.0, "fft_anisotropy": 0.1},
        "subject_sharpness": {"score": 0.45, "laplacian_var": 40.0, "fft_anisotropy": 0.1},
        "exposure": {"mean_luma": 128.0, "dynamic_range": 180.0},
        "eyes": {"faces": 1, "any_closed": False, "min_ear": 0.3},
        "composition": {},
        "decoded_size": [2000, 1333],
    }
    small = dict(metrics, subjects=[{"kind": "face", "bbox": [0, 0, 100, 100]}])
    large = dict(metrics, subjects=[{"kind": "face", "bbox": [0, 0, 1400, 1400]}])
    # Large face below threshold → soft → reject; small face below its scaled
    # (lower) threshold → not flagged soft → review (just slightly soft).
    assert decide(large).verdict == "reject"
    assert decide(small).verdict == "review"
