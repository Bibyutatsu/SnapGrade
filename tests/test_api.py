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


def test_select_photos_library(client):
    # CSRF guard check
    response = client.post("/api/select_photos_library")
    assert response.status_code == 403

    response = client.post("/api/select_photos_library", headers={"X-SnapGrade": "1"})
    assert response.status_code == 200
    data = response.json()
    assert "paths" in data
    assert len(data["paths"]) == 1


def test_api_duplicates(client):
    conn = db.connect()
    lib_id_1 = db.ensure_library(conn, "/fake/lib1")
    lib_id_2 = db.ensure_library(conn, "/fake/lib2")

    img_id_1 = db.upsert_image(
        conn,
        {
            "path": "/fake/lib1/image1.jpg",
            "size_bytes": 100,
            "mtime": 10.0,
            "library_id": lib_id_1,
            "phash": "ffffff",
            "dhash": "aaaaaa",
        }
    )
    db.save_metrics(conn, img_id_1, {"hashes": {"phash": "ffffff", "dhash": "aaaaaa"}})

    img_id_2 = db.upsert_image(
        conn,
        {
            "path": "/fake/lib2/image2.jpg",
            "size_bytes": 100,
            "mtime": 10.0,
            "library_id": lib_id_2,
            "phash": "fffff0",
            "dhash": "aaaaaa",
        }
    )
    db.save_metrics(conn, img_id_2, {"hashes": {"phash": "fffff0", "dhash": "aaaaaa"}})

    response = client.get("/api/duplicates")
    assert response.status_code == 200
    data = response.json()
    assert "groups" in data
    assert len(data["groups"]) == 1

    group = data["groups"][0]
    assert len(group["images"]) == 2
    paths = {img["path"] for img in group["images"]}
    assert paths == {"/fake/lib1/image1.jpg", "/fake/lib2/image2.jpg"}


def test_api_empty_and_restore_trash(client, tmp_path):
    import sys
    # CSRF guard check
    response = client.post("/api/trash/empty")
    assert response.status_code == 403

    if sys.platform != "darwin":
        response = client.post("/api/trash/empty", headers={"X-SnapGrade": "1"})
        assert response.status_code == 501
        
        response = client.post("/api/trash/restore", headers={"X-SnapGrade": "1"})
        assert response.status_code == 501
        return

    conn = db.connect()
    lib_id = db.ensure_library(conn, str(tmp_path))

    # Create dummy image file
    img_file = tmp_path / "reject.jpg"
    img_file.write_text("dummy jpeg content")

    img_id = db.upsert_image(
        conn,
        {
            "path": str(img_file),
            "size_bytes": 10,
            "mtime": 100.0,
            "library_id": lib_id,
        }
    )
    db.save_verdict(conn, img_id, "reject", 0, "red", ["blurry"])

    # Create photoslibrary dummy path that must be skipped/unimpacted
    photoslib_file = tmp_path / "test.photoslibrary" / "originals" / "safety.jpg"
    photoslib_file.parent.mkdir(parents=True, exist_ok=True)
    photoslib_file.write_text("photos library source content")

    img_id_photoslib = db.upsert_image(
        conn,
        {
            "path": str(photoslib_file),
            "size_bytes": 15,
            "mtime": 101.0,
            "library_id": lib_id,
        }
    )
    db.save_verdict(conn, img_id_photoslib, "reject", 0, "red", [])

    # Empty trash
    response = client.post("/api/trash/empty", headers={"X-SnapGrade": "1"})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1  # only 1 image (reject.jpg) should be deleted
    assert data["trashed_files"] == 1
    assert data["skipped_photoslibrary"] == 1

    # Verify standard image deleted from database
    row = conn.execute("SELECT 1 FROM images WHERE id=?", (img_id,)).fetchone()
    assert row is None

    # Verify photoslibrary image was NOT deleted from database
    row_photoslib = conn.execute("SELECT 1 FROM images WHERE id=?", (img_id_photoslib,)).fetchone()
    assert row_photoslib is not None

    # Verify standard image file is not at original path (wait for async recycle to finish)
    import time
    trash_dir = Path("~/.Trash").expanduser()
    trash_file = trash_dir / img_file.name
    for _ in range(30):
        if not img_file.exists() and trash_file.exists():
            break
        time.sleep(0.1)

    assert not img_file.exists()

    # Verify photoslibrary image file STILL exists
    assert photoslib_file.exists()

    # Now test RESTORE
    response = client.post("/api/trash/restore", headers={"X-SnapGrade": "1"})
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1

    # Verify standard image file is back at original path
    assert img_file.exists()

    # Verify database rows are restored
    restored_row = conn.execute("SELECT id, path FROM images WHERE path=?", (str(img_file),)).fetchone()
    assert restored_row is not None
    restored_id = int(restored_row["id"])

    # Verify verdict is restored
    verdict = conn.execute("SELECT verdict, stars, label FROM verdicts WHERE image_id=?", (restored_id,)).fetchone()
    assert verdict is not None
    assert verdict["verdict"] == "reject"
    assert verdict["stars"] == 0
    assert verdict["label"] == "red"


