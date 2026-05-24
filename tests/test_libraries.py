"""Smoke tests for the libraries table, cascade delete, and API guards."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException


def _fresh_db(tmp_path: Path, monkeypatch) -> Path:
    """Point the default DB at a fresh tmp path so tests don't touch ~/.snapgrade.

    The `connect` default is bound at function-definition time, so we both patch
    the module attribute *and* override the default kwarg via a wrapper.
    """
    from snapgrade import db as db_mod

    db_path = tmp_path / "library.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", db_path)
    real_connect = db_mod.connect
    monkeypatch.setattr(db_mod, "connect", lambda path=db_path: real_connect(path))
    return db_path


def test_ensure_library_idempotent(tmp_path, monkeypatch):
    from snapgrade import db

    _fresh_db(tmp_path, monkeypatch)
    conn = db.connect()
    a = db.ensure_library(conn, "/x/y")
    b = db.ensure_library(conn, "/x/y")
    assert a == b
    libs = db.list_libraries(conn)
    assert len(libs) == 1
    assert libs[0]["root_path"] == "/x/y"


def test_delete_library_cascades_images(tmp_path, monkeypatch):
    from snapgrade import db

    _fresh_db(tmp_path, monkeypatch)
    conn = db.connect()
    lib_id = db.ensure_library(conn, "/x/y")
    img_id = db.upsert_image(
        conn,
        {"path": "/x/y/a.jpg", "size_bytes": 1, "mtime": 1.0, "library_id": lib_id},
    )
    db.save_metrics(conn, img_id, {"k": 1})
    db.save_verdict(conn, img_id, "keeper", 5, None, [])
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 1

    counts = db.delete_library(conn, lib_id)
    assert counts["images"] == 1
    assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
    # FK cascade nukes metrics + verdicts too.
    assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 0


def test_ingest_rejects_empty_folder(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from fastapi import BackgroundTasks
    from snapgrade import api as api_mod

    for bad in ([], ["", "   "], ["/no/such/folder/xyz"]):
        with pytest.raises(HTTPException) as exc:
            api_mod.ingest(BackgroundTasks(), api_mod.IngestRequest(folders=bad))
        assert exc.value.status_code == 400
        assert "existing folder required" in str(exc.value.detail)


def test_stats_includes_libraries_count(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    from snapgrade import api as api_mod, db

    conn = db.connect()
    db.ensure_library(conn, "/a")
    db.ensure_library(conn, "/b")

    body = api_mod.stats()
    assert body["libraries"] == 2
    assert body["folders"] == 2  # back-compat alias


def test_set_library_models_merges_run(tmp_path, monkeypatch):
    from snapgrade import db

    _fresh_db(tmp_path, monkeypatch)
    conn = db.connect()
    lib_id = db.ensure_library(conn, "/x")
    db.set_library_models(conn, lib_id, models_pending=["scene"])
    db.set_library_models(conn, lib_id, models_run={"scene": "2026-05-20"}, models_pending=[])
    db.set_library_models(conn, lib_id, models_run={"objects": "2026-05-21"})
    libs = db.list_libraries(conn)
    assert libs[0]["models_run"] == {"scene": "2026-05-20", "objects": "2026-05-21"}
    assert libs[0]["models_pending"] == []


def test_api_animal_merging(tmp_path, monkeypatch):
    from snapgrade import api as api_mod, db

    _fresh_db(tmp_path, monkeypatch)

    conn = db.connect()
    lib_id = db.ensure_library(conn, "/x/y")
    img_id = db.upsert_image(
        conn,
        {"path": "/x/y/a.jpg", "size_bytes": 1, "mtime": 1.0, "library_id": lib_id},
    )

    # Save metrics with:
    # 1. Existing animals list (e.g. detected by Apple Vision: dog)
    # 2. YOLO objects detections (e.g. bird, car, and person)
    db.save_metrics(conn, img_id, {
        "animals": [{"species": "dog", "confidence": 0.8}],
        "objects": {
            "detections": [
                {"class": "bird", "conf": 0.9, "bbox": [0, 0, 10, 10]},
                {"class": "car", "conf": 0.8, "bbox": [10, 10, 20, 20]},
                {"class": "dog", "conf": 0.7, "bbox": [20, 20, 30, 30]} # Duplicate, should not be duplicated
            ]
        }
    })
    db.save_verdict(conn, img_id, "keeper", 5, None, [])

    # Test list_images
    res = api_mod.list_images(
        verdict=None,
        burst=None,
        folder=None,
        library_id=None,
        content_type=None,
        limit=10,
        offset=0
    )
    assert len(res["items"]) == 1
    item = res["items"][0]

    # Animals should contain both dog (original) and bird (from YOLO), but not duplicate dog, nor car (not an animal)
    animals = item["animals"]
    assert len(animals) == 2
    species = {a["species"] for a in animals}
    assert species == {"dog", "bird"}

    # Test get_image
    img_detail = api_mod.get_image(img_id)
    detail_animals = img_detail["metrics"]["animals"]
    assert len(detail_animals) == 2
    detail_species = {a["species"] for a in detail_animals}
    assert detail_species == {"dog", "bird"}

