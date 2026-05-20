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
