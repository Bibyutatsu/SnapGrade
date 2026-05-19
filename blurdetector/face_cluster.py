"""Face clustering across the library via InsightFace embeddings.

Optional Phase-4 feature — only runs if `insightface` is importable. We use
the lightweight `buffalo_s` pack (~17 MB) and cluster embeddings with a
greedy cosine-similarity threshold (no sklearn dependency).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import db, decode

_APP = None


@dataclass(frozen=True)
class FaceClusterConfig:
    similarity_threshold: float = 0.45   # cosine-similarity cutoff for "same person"
    max_edge: int = 1024


def _app():
    global _APP
    if _APP is None:
        from insightface.app import FaceAnalysis

        _APP = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
        _APP.prepare(ctx_id=-1, det_size=(640, 640))
    return _APP


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY,
            image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
            bbox TEXT NOT NULL,
            embedding BLOB NOT NULL,
            cluster_id INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_faces_image ON faces(image_id);
        CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
        """
    )


def detect_and_store(conn: sqlite3.Connection, cfg: FaceClusterConfig | None = None) -> int:
    cfg = cfg or FaceClusterConfig()
    _ensure_schema(conn)
    app = _app()
    rows = conn.execute(
        "SELECT i.id, i.path FROM images i "
        "LEFT JOIN faces f ON f.image_id = i.id "
        "WHERE f.id IS NULL"
    ).fetchall()
    inserted = 0
    for r in rows:
        try:
            img = decode.decode(Path(r["path"]), max_edge=cfg.max_edge)
            faces = app.get(img.rgb[:, :, ::-1])  # insightface wants BGR
        except Exception:
            continue
        with db.transaction(conn):
            for face in faces:
                bbox = [int(x) for x in face.bbox.tolist()]
                emb = np.asarray(face.normed_embedding, dtype=np.float32).tobytes()
                conn.execute(
                    "INSERT INTO faces(image_id, bbox, embedding) VALUES(?,?,?)",
                    (int(r["id"]), json.dumps(bbox), emb),
                )
                inserted += 1
    return inserted


def cluster(conn: sqlite3.Connection, cfg: FaceClusterConfig | None = None) -> int:
    cfg = cfg or FaceClusterConfig()
    _ensure_schema(conn)
    rows = conn.execute("SELECT id, embedding FROM faces").fetchall()
    if not rows:
        return 0
    ids = [int(r["id"]) for r in rows]
    embs = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    n = len(ids)
    cluster_ids = [-1] * n
    centroids: list[np.ndarray] = []
    centroid_counts: list[int] = []

    # Greedy single-pass clustering — O(N*K) where K is cluster count, fine for
    # a personal library and avoids pulling in sklearn/hdbscan.
    for i in range(n):
        v = embs[i]
        best_c, best_sim = -1, -1.0
        for c, mu in enumerate(centroids):
            sim = float(np.dot(v, mu))
            if sim > best_sim:
                best_sim, best_c = sim, c
        if best_sim >= cfg.similarity_threshold:
            cluster_ids[i] = best_c
            k = centroid_counts[best_c]
            centroids[best_c] = (centroids[best_c] * k + v) / (k + 1)
            centroids[best_c] = centroids[best_c] / max(np.linalg.norm(centroids[best_c]), 1e-6)
            centroid_counts[best_c] = k + 1
        else:
            cluster_ids[i] = len(centroids)
            centroids.append(v.copy())
            centroid_counts.append(1)

    with db.transaction(conn):
        for fid, cid in zip(ids, cluster_ids):
            conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (int(cid), fid))
    return len(centroids)
