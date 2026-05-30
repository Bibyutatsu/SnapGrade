from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from snapgrade.api import app
from snapgrade import db


def _fresh_db(tmp_path: Path, monkeypatch) -> Path:
    from snapgrade import db as db_mod

    db_path = tmp_path / "library.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", db_path)
    real_connect = db_mod.connect
    monkeypatch.setattr(db_mod, "connect", lambda path=db_path: real_connect(path))
    return db_path


@pytest.fixture
def client(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    with TestClient(app) as c:
        yield c


def test_api_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_stats(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "images" in data
    assert "folders" in data
    assert "libraries" in data
    assert "by_verdict" in data


def test_api_images_pagination(client):
    conn = db.connect()
    lib_id = db.ensure_library(conn, "/fake/lib")
    
    db.upsert_image(
        conn,
        {"path": "/fake/lib/1.jpg", "size_bytes": 10, "mtime": 100.0, "library_id": lib_id},
    )
    db.upsert_image(
        conn,
        {"path": "/fake/lib/2.jpg", "size_bytes": 20, "mtime": 101.0, "library_id": lib_id},
    )
    
    response = client.get("/api/images?limit=1&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 1
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 0

    response = client.get("/api/images?limit=1&offset=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 1


def test_api_verdict_csrf_and_update(client):
    conn = db.connect()
    lib_id = db.ensure_library(conn, "/fake/lib")
    img_id = db.upsert_image(
        conn,
        {"path": "/fake/lib/1.jpg", "size_bytes": 10, "mtime": 100.0, "library_id": lib_id},
    )
    db.save_verdict(conn, img_id, "review", 3, None, [])

    # POST without X-SnapGrade header should fail with 403 (CSRF Guard)
    response = client.post(f"/api/images/{img_id}/verdict", json={"verdict": "keeper", "stars": 5})
    assert response.status_code == 403
    assert "CSRF guard" in response.json()["detail"]

    # POST with X-SnapGrade header should succeed
    response = client.post(
        f"/api/images/{img_id}/verdict",
        json={"verdict": "keeper", "stars": 5},
        headers={"X-SnapGrade": "1"}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    # Verify update in DB
    verdict = conn.execute("SELECT verdict, stars FROM verdicts WHERE image_id=?", (img_id,)).fetchone()
    assert verdict["verdict"] == "keeper"
    assert verdict["stars"] == 5
