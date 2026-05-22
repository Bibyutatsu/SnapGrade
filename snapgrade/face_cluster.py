"""Face clustering across the library via InsightFace embeddings.

Optional Phase-4 feature — only runs if `insightface` is importable. We use
the lightweight `buffalo_s` pack (~17 MB) and cluster embeddings with a
greedy cosine-similarity threshold (no sklearn dependency).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import db, decode

log = logging.getLogger(__name__)

_APP = None

# Faces flushed per transaction — mirrors pipeline.PERSIST_BATCH so detection
# pays one BEGIN/COMMIT per ~50 faces instead of one per image.
PERSIST_BATCH = 50


@dataclass(frozen=True)
class FaceClusterConfig:
    # Cosine-similarity cutoff for "same person". Calibrated against InsightFace
    # `buffalo_s` (mobile) embeddings — typical same-person pairs land in
    # ~0.30–0.60, different-person noise stays under ~0.20. Larger models
    # (buffalo_l) can use 0.40+ comfortably.
    similarity_threshold: float = 0.30
    max_edge: int = 1024


def _app():
    global _APP
    if _APP is None:
        from insightface.app import FaceAnalysis

        # Prefer CoreML (ANE/GPU) on Apple Silicon, falling back to CPU. ORT
        # silently drops providers it can't construct, so listing CoreML first
        # is safe on machines without it.
        try:
            import onnxruntime as ort
            available = set(ort.get_available_providers())
        except Exception:
            available = set()
        providers = (
            ["CoreMLExecutionProvider", "CPUExecutionProvider"]
            if "CoreMLExecutionProvider" in available
            else ["CPUExecutionProvider"]
        )
        _APP = FaceAnalysis(name="buffalo_s", providers=providers)
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
    """FIQA-style face quality score in [0, 1].

    Combines detector confidence, frame coverage, crop sharpness, and pose
    frontality — the canonical FIQA inputs. InsightFace's `Face.pose` is
    (pitch, yaw, roll) in degrees when the model is available; frontal faces
    (|yaw|, |pitch| ≲ 15°) get full pose credit.
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

    pose = getattr(face, "pose", None)
    pose_score = 1.0
    if pose is not None:
        try:
            pitch, yaw, _roll = (float(v) for v in pose[:3])
            # Frontal gets 1.0, ±45° drops to 0. Linear decay; profile shots
            # (>45°) get 0 — by far the most common "bad photo" failure mode.
            pose_score = max(0.0, 1.0 - max(abs(pitch), abs(yaw)) / 45.0)
        except (TypeError, ValueError):
            pose_score = 1.0

    return float(0.3 * det + 0.2 * size_score + 0.3 * sharp_score + 0.2 * pose_score)


def detect_and_store(
    conn: sqlite3.Connection,
    cfg: FaceClusterConfig | None = None,
    progress_cb=None,
) -> int:
    cfg = cfg or FaceClusterConfig()
    _ensure_schema(conn)
    app = _app()
    rows = conn.execute(
        "SELECT i.id, i.path FROM images i "
        "LEFT JOIN faces f ON f.image_id = i.id "
        "WHERE f.id IS NULL"
    ).fetchall()
    total = len(rows)
    if progress_cb is not None:
        progress_cb(0, total)
    inserted = 0
    batch: list[tuple[int, str, bytes, float]] = []

    def _flush() -> None:
        nonlocal inserted
        if not batch:
            return
        with db.transaction(conn):
            conn.executemany(
                "INSERT INTO faces(image_id, bbox, embedding, quality) VALUES(?,?,?,?)",
                batch,
            )
        inserted += len(batch)
        batch.clear()

    for i, r in enumerate(rows, start=1):
        try:
            img = decode.decode(Path(r["path"]), max_edge=cfg.max_edge)
            faces = app.get(img.rgb[:, :, ::-1])  # insightface wants BGR
            for face in faces:
                bbox = [int(x) for x in face.bbox.tolist()]
                emb = np.asarray(face.normed_embedding, dtype=np.float32).tobytes()
                quality = _face_quality(face, img.rgb)
                batch.append((int(r["id"]), json.dumps(bbox), emb, quality))
            if len(batch) >= PERSIST_BATCH:
                _flush()
        except Exception as e:
            log.warning("face detect failed for %s: %s", r["path"], e)
        if progress_cb is not None:
            progress_cb(i, total)
    _flush()
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


def best_photo_for_cluster(conn: sqlite3.Connection, cluster_id: int) -> dict | None:
    """Highest-quality face row for a single cluster, or None if empty."""
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT image_id, bbox, quality FROM faces "
        "WHERE cluster_id = ? AND quality IS NOT NULL "
        "ORDER BY quality DESC LIMIT 1",
        (int(cluster_id),),
    ).fetchone()
    if row is None:
        return None
    return {
        "image_id": int(row["image_id"]),
        "quality": float(row["quality"]),
        "bbox": json.loads(row["bbox"]),
    }


# ── Cluster curation: labels, merge, split, threshold preview ─────────────────
def get_labels(conn: sqlite3.Connection) -> dict[int, str]:
    """{cluster_id: label} for all named clusters."""
    rows = conn.execute("SELECT cluster_id, label FROM cluster_labels").fetchall()
    return {int(r["cluster_id"]): r["label"] for r in rows}


def set_label(conn: sqlite3.Connection, cluster_id: int, label: str) -> None:
    """Name (or rename) a cluster. Empty label clears the name."""
    from datetime import datetime as _dt, timezone as _tz
    label = (label or "").strip()
    if not label:
        conn.execute("DELETE FROM cluster_labels WHERE cluster_id=?", (cluster_id,))
        return
    conn.execute(
        "INSERT INTO cluster_labels(cluster_id, label, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(cluster_id) DO UPDATE SET label=excluded.label, updated_at=excluded.updated_at",
        (cluster_id, label, _dt.now(_tz.utc).isoformat()),
    )


def merge_clusters(conn: sqlite3.Connection, into: int, frm: int) -> int:
    """Fold cluster `frm` into `into`. Returns the number of faces moved. Carries
    `frm`'s label to `into` only if `into` is unnamed."""
    if into == frm:
        return 0
    with db.transaction(conn):
        cur = conn.execute(
            "UPDATE faces SET cluster_id=? WHERE cluster_id=?", (into, frm)
        )
        labels = get_labels(conn)
        if frm in labels and into not in labels:
            set_label(conn, into, labels[frm])
        conn.execute("DELETE FROM cluster_labels WHERE cluster_id=?", (frm,))
    return cur.rowcount or 0


def set_face_cluster(conn: sqlite3.Connection, face_id: int, cluster_id: int | None) -> bool:
    """Reassign a single face to another cluster, or remove it from clustering
    (cluster_id=None). Returns False if the face id is unknown."""
    row = conn.execute("SELECT 1 FROM faces WHERE id=?", (face_id,)).fetchone()
    if not row:
        return False
    conn.execute("UPDATE faces SET cluster_id=? WHERE id=?", (cluster_id, face_id))
    return True


def preview_cluster_count(conn: sqlite3.Connection, threshold: float) -> dict[str, int]:
    """Cluster count at a candidate threshold WITHOUT persisting — powers the
    '≈N clusters' slider hint. Reuses the same HNSW/greedy path as cluster()."""
    _ensure_schema(conn)
    rows = conn.execute("SELECT embedding FROM faces").fetchall()
    if not rows:
        return {"faces": 0, "clusters": 0}
    embs = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    try:
        import hnswlib  # noqa: F401
        cluster_ids = _hnsw_cluster(embs, threshold)
    except Exception:
        cluster_ids = _greedy_cluster(embs, threshold)
    return {"faces": len(embs), "clusters": len(set(cluster_ids))}


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
        conn.executemany(
            "UPDATE faces SET cluster_id=? WHERE id=?",
            [(int(cid), fid) for fid, cid in zip(ids, cluster_ids)],
        )
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
