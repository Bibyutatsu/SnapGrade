"""Unit tests for the burst best-of-burst quality scoring."""

from __future__ import annotations

from snapgrade.group import BurstConfig, _quality_score


def _frame(sharp=0.5, any_closed=False, max_blink=0.0, max_smile=0.0, faces=1, expo_ok=True, aesthetic=0.5):
    return {
        "subject_sharpness": {"score": sharp},
        "eyes": {
            "faces": faces,
            "any_closed": any_closed,
            "max_blink": max_blink,
            "max_smile": max_smile,
        },
        "exposure": {"overexposed": not expo_ok, "underexposed": False},
        "aesthetic_score": aesthetic,
    }


def test_open_eyes_beat_closed_eyes():
    cfg = BurstConfig()
    closed = _frame(any_closed=True, max_blink=0.9)
    open_ = _frame(any_closed=False, max_blink=0.05)
    assert _quality_score(open_, cfg) > _quality_score(closed, cfg)


def test_smile_breaks_a_tie():
    """Two equally-sharp, equally-open frames — the smiling one should win."""
    cfg = BurstConfig()
    neutral = _frame(max_smile=0.0)
    smiling = _frame(max_smile=0.9)
    assert _quality_score(smiling, cfg) > _quality_score(neutral, cfg)


def test_continuous_eye_signal_prefers_wider_open():
    """Neither closed, but lower blink (wider open) should score higher."""
    cfg = BurstConfig()
    droopy = _frame(max_blink=0.4)
    wide = _frame(max_blink=0.02)
    assert _quality_score(wide, cfg) > _quality_score(droopy, cfg)


def test_no_face_does_not_penalize():
    """Faceless frames get full eye credit so landscapes aren't dragged down."""
    cfg = BurstConfig()
    faceless = _frame(faces=0)
    # eye term contributes its full weight
    assert _quality_score(faceless, cfg) >= cfg.w_eyes
