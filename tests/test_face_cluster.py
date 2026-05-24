"""Face clustering (HNSW full + incremental) on synthetic embeddings.

Bypasses InsightFace detection by inserting face rows directly, so it runs
without the optional models.
"""

from __future__ import annotations

import json

import numpy as np

from snapgrade import db, face_cluster


def _seed_faces(conn, vectors):
    lib = db.ensure_library(conn, "/x")
    img = db.upsert_image(conn, {"path": "/x/a.jpg", "size_bytes": 1, "mtime": 1.0, "library_id": lib})
    fc = face_cluster
    fc._ensure_schema(conn)
    for v in vectors:
        v = (v / np.linalg.norm(v)).astype(np.float32)
        conn.execute(
            "INSERT INTO faces(image_id, bbox, embedding, quality) VALUES(?,?,?,?)",
            (img, json.dumps([0, 0, 10, 10]), v.tobytes(), 0.5),
        )
    conn.commit()


def _three_blobs(dim=128, per=8, seed=0):
    rng = np.random.default_rng(seed)
    centers = [rng.normal(size=dim) for _ in range(3)]
    vecs = []
    for c in centers:
        for _ in range(per):
            vecs.append(c + 0.02 * rng.normal(size=dim))
    return vecs, centers


def test_full_cluster_finds_three_groups(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    vecs, _ = _three_blobs()
    _seed_faces(conn, vecs)

    n = face_cluster.cluster(conn)
    assert n == 3, f"expected 3 clusters, got {n}"
    # Every face assigned.
    unassigned = conn.execute("SELECT COUNT(*) FROM faces WHERE cluster_id IS NULL").fetchone()[0]
    assert unassigned == 0


def test_incremental_attaches_to_existing(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    vecs, centers = _three_blobs()
    _seed_faces(conn, vecs)
    face_cluster.cluster(conn)
    n_before = conn.execute("SELECT COUNT(DISTINCT cluster_id) FROM faces").fetchone()[0]

    # Add new faces near existing center 0 and one far-away novel identity.
    rng = np.random.default_rng(1)
    near = centers[0] + 0.02 * rng.normal(size=128)
    novel = rng.normal(size=128) * 5
    _seed_faces(conn, [near, novel])

    res = face_cluster.cluster_incremental(conn)
    assert res["assigned_existing"] >= 1   # the near one joined an existing cluster
    assert res["new_clusters"] >= 1        # the novel one opened a new cluster
    n_after = conn.execute("SELECT COUNT(DISTINCT cluster_id) FROM faces").fetchone()[0]
    assert n_after == n_before + res["new_clusters"]
    assert conn.execute("SELECT COUNT(*) FROM faces WHERE cluster_id IS NULL").fetchone()[0] == 0


def test_label_merge_split_preview(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    vecs, _ = _three_blobs()
    _seed_faces(conn, vecs)
    face_cluster.cluster(conn)
    cids = sorted({int(r[0]) for r in conn.execute("SELECT cluster_id FROM faces").fetchall()})
    assert len(cids) == 3

    # Label round-trips.
    face_cluster.set_label(conn, cids[0], "Mom")
    assert face_cluster.get_labels(conn)[cids[0]] == "Mom"

    # Merge folds one cluster's faces into another and carries the label when the
    # target is unnamed.
    face_cluster.set_label(conn, cids[1], "Dad")
    moved = face_cluster.merge_clusters(conn, into=cids[2], frm=cids[1])
    assert moved > 0
    assert face_cluster.get_labels(conn).get(cids[2]) == "Dad"
    assert cids[1] not in face_cluster.get_labels(conn)
    assert conn.execute("SELECT COUNT(*) FROM faces WHERE cluster_id=?", (cids[1],)).fetchone()[0] == 0

    # Split: remove a single face from clustering.
    fid = conn.execute("SELECT id FROM faces WHERE cluster_id=?", (cids[0],)).fetchone()[0]
    assert face_cluster.set_face_cluster(conn, fid, None) is True
    assert conn.execute("SELECT cluster_id FROM faces WHERE id=?", (fid,)).fetchone()[0] is None
    assert face_cluster.set_face_cluster(conn, 999999, None) is False

    # Preview clusters without persisting — a tight threshold yields >= the
    # current grouping and writes nothing.
    before = conn.execute("SELECT cluster_id FROM faces").fetchall()
    prev = face_cluster.preview_cluster_count(conn, 0.9)
    assert prev["faces"] == len(vecs)
    assert prev["clusters"] >= 1
    after = conn.execute("SELECT cluster_id FROM faces").fetchall()
    assert before == after


def test_labels_survive_recluster(tmp_path, monkeypatch):
    """A named cluster keeps its name after a full re-cluster at a new threshold,
    via centroid nearest-match re-anchoring (Phase 5)."""
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    vecs, centers = _three_blobs(per=8, seed=3)
    _seed_faces(conn, vecs)
    face_cluster.cluster(conn)

    # Name each of the three clusters after the person at its centroid.
    names = {}
    for cid in sorted({int(r[0]) for r in conn.execute("SELECT cluster_id FROM faces")}):
        # representative embedding for this cluster
        row = conn.execute("SELECT embedding FROM faces WHERE cluster_id=? LIMIT 1", (cid,)).fetchone()
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        # which blob center is this closest to
        nearest = int(np.argmax([float(np.dot(emb, c / np.linalg.norm(c))) for c in centers]))
        name = f"person-{nearest}"
        face_cluster.set_label(conn, cid, name)
        names[cid] = name
    assert len(set(names.values())) == 3

    # Re-cluster (renumbers cluster ids). Labels must re-anchor to the same people.
    face_cluster.cluster(conn, face_cluster.FaceClusterConfig(similarity_threshold=0.5))
    new_labels = set(face_cluster.get_labels(conn).values())
    assert new_labels == {"person-0", "person-1", "person-2"}, new_labels


def test_set_burst_best(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    lib = db.ensure_library(conn, "/b")
    ids = [db.upsert_image(conn, {"path": f"/b/{i}.jpg", "size_bytes": 1, "mtime": 1.0, "library_id": lib}) for i in range(3)]
    conn.execute("INSERT INTO bursts(created_at) VALUES('t')")
    bid = conn.execute("SELECT id FROM bursts").fetchone()[0]
    for i, iid in enumerate(ids):
        conn.execute("INSERT INTO burst_members(burst_id, image_id, is_best) VALUES(?,?,?)", (bid, iid, 1 if i == 0 else 0))
    conn.commit()

    assert db.set_burst_best(conn, bid, ids[2]) is True
    best = conn.execute("SELECT image_id FROM burst_members WHERE burst_id=? AND is_best=1", (bid,)).fetchall()
    assert [r[0] for r in best] == [ids[2]]
    # Image not in the burst → False, nothing changes.
    assert db.set_burst_best(conn, bid, 999999) is False
    best = conn.execute("SELECT image_id FROM burst_members WHERE burst_id=? AND is_best=1", (bid,)).fetchall()
    assert [r[0] for r in best] == [ids[2]]


def test_detect_and_store_filtering(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    from snapgrade import face_cluster
    from snapgrade import decode

    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)

    lib = db.ensure_library(conn, "/b")

    # 1. Image with face
    img_face = db.upsert_image(conn, {"path": "/b/face.jpg", "size_bytes": 1, "mtime": 1.0, "library_id": lib})
    db.save_metrics(conn, img_face, {
        "subjects": [{"kind": "face", "bbox": [0, 0, 10, 10]}]
    })

    # 2. Image without face (scene)
    img_scene = db.upsert_image(conn, {"path": "/b/scene.jpg", "size_bytes": 1, "mtime": 1.0, "library_id": lib})
    db.save_metrics(conn, img_scene, {
        "subjects": [{"kind": "saliency", "bbox": [0, 0, 10, 10]}]
    })

    # Mock _app() and decode.decode
    class MockFace:
        def __init__(self):
            self.bbox = np.array([0, 0, 5, 5])
            self.normed_embedding = np.ones(128, dtype=np.float32)
            self.det_score = 0.9

    class MockApp:
        def __init__(self):
            self.calls = []
        def get(self, img_bgr):
            self.calls.append(img_bgr)
            return [MockFace()]

    mock_app = MockApp()
    monkeypatch.setattr(face_cluster, "_app", lambda: mock_app)

    class MockDecoded:
        def __init__(self):
            self.rgb = np.zeros((100, 100, 3), dtype=np.uint8)

    monkeypatch.setattr(decode, "decode", lambda path, max_edge: MockDecoded())

    # Run detect_and_store
    n = face_cluster.detect_and_store(conn)

    # Only face.jpg should have been processed, so n should be 1
    assert n == 1
    assert len(mock_app.calls) == 1

    # Check that faces table has the face for img_face but not for img_scene
    faces = conn.execute("SELECT image_id FROM faces").fetchall()
    assert [r[0] for r in faces] == [img_face]


def test_detect_and_store_lazy_app_loading(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    from snapgrade import face_cluster

    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)

    lib = db.ensure_library(conn, "/b")

    # Image without face
    img_scene = db.upsert_image(conn, {"path": "/b/scene.jpg", "size_bytes": 1, "mtime": 1.0, "library_id": lib})
    db.save_metrics(conn, img_scene, {
        "subjects": [{"kind": "saliency", "bbox": [0, 0, 10, 10]}]
    })

    app_called = False
    def mock_app_fn():
        nonlocal app_called
        app_called = True
        raise RuntimeError("Should not be called")

    monkeypatch.setattr(face_cluster, "_app", mock_app_fn)

    n = face_cluster.detect_and_store(conn)
    assert n == 0
    assert not app_called

