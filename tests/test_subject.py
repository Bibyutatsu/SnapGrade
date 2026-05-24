from __future__ import annotations

from snapgrade.metrics import subject
from snapgrade.metrics.subject import Subject


def test_primary_subjects_saliency_fallback():
    # 1. Fallback to salient bbox when no faces are detected
    res = subject.primary_subjects(
        subjects=[],
        image_shape=(1000, 1000),
        salient_bbox=[100, 100, 200, 200],  # tight salient box (area = 10000 <= 250000)
    )
    assert len(res) == 1
    assert res[0].kind == "saliency"
    assert res[0].bbox == (100, 100, 100, 100)


def test_primary_subjects_person_fallback():
    # 2. Fallback to person bbox when no faces are detected
    res = subject.primary_subjects(
        subjects=[],
        image_shape=(1000, 1000),
        person_bboxes=[[150, 150, 250, 250]],
    )
    assert len(res) == 1
    assert res[0].kind == "person"
    assert res[0].bbox == (150, 150, 100, 100)


def test_primary_subjects_combined_fallback():
    # 3. Fallback to the largest of salient and person bboxes
    res = subject.primary_subjects(
        subjects=[],
        image_shape=(1000, 1000),
        salient_bbox=[100, 100, 250, 250],  # 150x150, area = 22500
        person_bboxes=[[150, 150, 200, 200]],  # 50x50, area = 2500
    )
    assert len(res) == 1
    assert res[0].kind == "saliency"
    assert res[0].bbox == (100, 100, 150, 150)

    # Larger person bbox than salient bbox
    res2 = subject.primary_subjects(
        subjects=[],
        image_shape=(1000, 1000),
        salient_bbox=[100, 100, 150, 150],  # 50x50, area = 2500
        person_bboxes=[[150, 150, 300, 300]],  # 150x150, area = 22500
    )
    assert len(res2) == 1
    assert res2[0].kind == "person"
    assert res2[0].bbox == (150, 150, 150, 150)
