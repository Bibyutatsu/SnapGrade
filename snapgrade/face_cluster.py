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
            cluster_id INTEGER,
            quality REAL
        );
        CREATE INDEX IF NOT EXISTS idx_faces_image ON faces(image_id);
        CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
        """
    )
    # Migrate older DBs that predate the quality column.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(faces)").fetchall()}
    if "quality" not in cols:
        conn.execute("ALTER TABLE faces ADD COLUMN quality REAL")


def _face_quality(face, rgb: np.ndarray) -> float:
    """Lightweight face-image-quality score in [0, 1].

    Combines detector confidence, on-frame face size, and crop sharpness — the
    signals that decide "best photo of this person". No extra model needed.
    """
    import cv2

    det = float(getattr(face, "det_score", 1.0) or 0.0)
    x0, y0, x1, y1 = (int(v) for v in face.bbox.tolist())
    h, w = rgb.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    area = max(0, x1 - x0) * max(0, y1 - y0)
    size_score = min(1.0, area / (w * h * 0.05))  # face covering ≥5% of frame = full credit

    sharp_score = 0.0
    crop = rgb[y0:y1, x0:x1]
    if crop.size and min(crop.shape[:2]) >= 8:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        # Normalize Laplacian variance into ~[0,1]; 500 ≈ crisp face.
        sharp_score = min(1.0, float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 500.0)

    return float(0.4 * det + 0.3 * size_score + 0.3 * sharp_score)


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
                quality = _face_quality(face, img.rgb)
                conn.execute(
                    "INSERT INTO faces(image_id, bbox, embedding, quality) VALUES(?,?,?,?)",
                    (int(r["id"]), json.dumps(bbox), emb, quality),
                )
                inserted += 1
    return inserted


def best_faces_per_cluster(conn: sqlite3.Connection) -> dict[int, dict]:
    """Return the highest-quality face per cluster: {cluster_id: {image_id, quality, bbox}}.

    Powers "best photo of person X" — pick the sharpest, largest, most
    confident face for each clustered identity.
    """
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT cluster_id, image_id, bbox, quality FROM faces "
        "WHERE cluster_id IS NOT NULL AND quality IS NOT NULL "
        "ORDER BY cluster_id, quality DESC"
    ).fetchall()
    best: dict[int, dict] = {}
    for r in rows:
        cid = int(r["cluster_id"])
        if cid not in best:  # first row per cluster is the highest quality
            best[cid] = {
                "image_id": int(r["image_id"]),
                "quality": float(r["quality"]),
                "bbox": json.loads(r["bbox"]),
            }
    return best


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _greedy_cluster(embs: np.ndarray, threshold: float) -> list[int]:
    """Original O(N*K) greedy centroid clustering — numpy fallback."""
    n = len(embs)
    cluster_ids = [-1] * n
    centroids: list[np.ndarray] = []
    counts: list[int] = []
    for i in range(n):
        v = embs[i]
        best_c, best_sim = -1, -1.0
        for c, mu in enumerate(centroids):
            sim = float(np.dot(v, mu))
            if sim > best_sim:
                best_sim, best_c = sim, c
        if best_sim >= threshold:
            cluster_ids[i] = best_c
            k = counts[best_c]
            centroids[best_c] = (centroids[best_c] * k + v) / (k + 1)
            centroids[best_c] /= max(np.linalg.norm(centroids[best_c]), 1e-6)
            counts[best_c] = k + 1
        else:
            cluster_ids[i] = len(centroids)
            centroids.append(v.copy())
            counts.append(1)
    return cluster_ids


def _hnsw_cluster(embs: np.ndarray, threshold: float) -> list[int]:
    """Single-linkage clustering via an HNSW neighbour graph — O(N log N).

    Connects each face to its near neighbours (cosine sim ≥ threshold) and takes
    connected components. Scales to 100k+ faces where the greedy O(N*K) scan
    bogs down.
    """
    import hnswlib

    n, dim = embs.shape
    index = hnswlib.Index(space="cosine", dim=dim)
    index.init_index(max_elements=n, ef_construction=200, M=16)
    index.add_items(embs, np.arange(n))
    index.set_ef(min(n, 64))

    uf = _UnionFind(n)
    k = min(n, 32)
    labels, distances = index.knn_query(embs, k=k)
    max_dist = 1.0 - threshold  # cosine distance = 1 - similarity
    for i in range(n):
        for j, d in zip(labels[i], distances[i]):
            if j != i and d <= max_dist:
                uf.union(i, int(j))

    # Compact component roots into 0..C-1 cluster ids.
    root_to_cid: dict[int, int] = {}
    out = [0] * n
    for i in range(n):
        r = uf.find(i)
        if r not in root_to_cid:
            root_to_cid[r] = len(root_to_cid)
        out[i] = root_to_cid[r]
    return out


def cluster(conn: sqlite3.Connection, cfg: FaceClusterConfig | None = None) -> int:
    """Full re-cluster of all faces. Uses HNSW when available, else greedy."""
    cfg = cfg or FaceClusterConfig()
    _ensure_schema(conn)
    rows = conn.execute("SELECT id, embedding FROM faces").fetchall()
    if not rows:
        return 0
    ids = [int(r["id"]) for r in rows]
    embs = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])

    try:
        import hnswlib  # noqa: F401
        cluster_ids = _hnsw_cluster(embs, cfg.similarity_threshold)
    except Exception:
        cluster_ids = _greedy_cluster(embs, cfg.similarity_threshold)

    with db.transaction(conn):
        for fid, cid in zip(ids, cluster_ids):
            conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (int(cid), fid))
    return len(set(cluster_ids))


def cluster_incremental(conn: sqlite3.Connection, cfg: FaceClusterConfig | None = None) -> dict[str, int]:
    """Assign only unclustered faces against existing clusters — no full rebuild.

    Each new face joins the cluster of its nearest already-clustered neighbour
    when cosine sim ≥ threshold, otherwise opens a new cluster. Newly assigned
    faces become candidates for subsequent ones in the same pass.
    """
    cfg = cfg or FaceClusterConfig()
    _ensure_schema(conn)
    clustered = conn.execute(
        "SELECT id, embedding, cluster_id FROM faces WHERE cluster_id IS NOT NULL"
    ).fetchall()
    pending = conn.execute(
        "SELECT id, embedding FROM faces WHERE cluster_id IS NULL"
    ).fetchall()
    if not pending:
        return {"assigned_existing": 0, "new_clusters": 0}
    if not clustered:
        # Nothing to attach to — fall back to a full cluster.
        n = cluster(conn, cfg)
        return {"assigned_existing": 0, "new_clusters": n}

    dim = len(np.frombuffer(clustered[0]["embedding"], dtype=np.float32))
    ref_embs = [np.frombuffer(r["embedding"], dtype=np.float32) for r in clustered]
    ref_cids = [int(r["cluster_id"]) for r in clustered]
    next_cid = max(ref_cids) + 1

    use_hnsw = False
    index = None
    try:
        import hnswlib
        index = hnswlib.Index(space="cosine", dim=dim)
        index.init_index(max_elements=len(ref_embs) + len(pending), ef_construction=200, M=16)
        index.add_items(np.stack(ref_embs), np.arange(len(ref_embs)))
        index.set_ef(64)
        use_hnsw = True
    except Exception:
        ref_matrix = np.stack(ref_embs)

    assigned = new = 0
    with db.transaction(conn):
        for r in pending:
            v = np.frombuffer(r["embedding"], dtype=np.float32)
            if use_hnsw:
                labels, distances = index.knn_query(v, k=1)
                nn_idx, sim = int(labels[0][0]), 1.0 - float(distances[0][0])
            else:
                sims = ref_matrix @ v
                nn_idx = int(sims.argmax())
                sim = float(sims[nn_idx])
            if sim >= cfg.similarity_threshold:
                cid = ref_cids[nn_idx]
                assigned += 1
            else:
                cid = next_cid
                next_cid += 1
                new += 1
            conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cid, int(r["id"])))
            # Make this face attachable for the rest of the pass.
            ref_cids.append(cid)
            if use_hnsw:
                index.add_items(v.reshape(1, -1), np.array([len(ref_cids) - 1]))
            else:
                ref_matrix = np.vstack([ref_matrix, v])
    return {"assigned_existing": assigned, "new_clusters": new}
