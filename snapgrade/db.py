"""SQLite layer — the single source of truth.

Schema:
  images        — one row per file, keyed by absolute path.
  metrics       — JSON blob of all computed metrics, keyed by image id.
  verdicts      — verdict + reasons + user overrides.

We store metrics as JSON rather than columns because the schema will grow as
we add metrics; using JSON keeps migrations free and the UI can read it
directly. SQLite handles JSON natively via the json1 extension.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = Path.home() / ".snapgrade" / "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY,
    root_path TEXT NOT NULL UNIQUE,
    display_name TEXT,
    added_at TEXT NOT NULL,
    models_run TEXT,        -- JSON object: {model_name: iso_timestamp}
    models_pending TEXT     -- JSON array of model names queued for next analyze
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    library_id INTEGER REFERENCES libraries(id) ON DELETE CASCADE,
    path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    content_hash TEXT,
    kind TEXT,
    width INTEGER,
    height INTEGER,
    capture_time TEXT,
    camera_make TEXT,
    camera_model TEXT,
    lens_model TEXT,
    iso INTEGER,
    f_number REAL,
    exposure_time REAL,
    focal_length_mm REAL,
    orientation INTEGER,
    gps_lat REAL,
    gps_lon REAL,
    phash TEXT,
    dhash TEXT,
    analyzed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_images_capture_time ON images(capture_time);
CREATE INDEX IF NOT EXISTS idx_images_phash ON images(phash);

CREATE TABLE IF NOT EXISTS metrics (
    image_id INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verdicts (
    image_id INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL,        -- keeper | review | reject
    stars INTEGER NOT NULL,       -- 1..5
    label TEXT,                   -- color label (red/yellow/green/blue/purple)
    reasons TEXT,                 -- JSON array of short strings
    user_override INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bursts (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS burst_members (
    burst_id INTEGER REFERENCES bursts(id) ON DELETE CASCADE,
    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
    is_best INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (burst_id, image_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_members (
    event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, image_id)
);
CREATE INDEX IF NOT EXISTS idx_event_members_image ON event_members(image_id);

CREATE TABLE IF NOT EXISTS image_embeddings (
    image_id INTEGER PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    model TEXT NOT NULL,        -- e.g. "mobileclip_s0"
    dim INTEGER NOT NULL,
    embedding BLOB NOT NULL     -- float32, L2-normalized
);

-- User-assigned names for face clusters. Keyed on the cluster_id integer, which
-- is reassigned by a full re-cluster — so labels belong to the current
-- clustering generation (the UI warns before reclustering).
CREATE TABLE IF NOT EXISTS cluster_labels (
    cluster_id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ImageRow:
    id: int
    path: str
    mtime: float
    analyzed_at: str | None


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # busy_timeout: when two connections write concurrently (e.g. an ingest and
    # a faces run), the loser waits up to 5s for the lock instead of failing
    # immediately with "database is locked". synchronous=NORMAL is the safe WAL
    # default for a local single-user cache; cache_size=-65536 gives a 64 MB page
    # cache. All three are essentially free perf / robustness wins.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_library_id(conn)
    return conn


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _migrate_library_id(conn: sqlite3.Connection) -> None:
    """Backfill library_id on images for DBs created before the libraries table."""
    if not _has_column(conn, "images", "library_id"):
        conn.execute("ALTER TABLE images ADD COLUMN library_id INTEGER REFERENCES libraries(id) ON DELETE CASCADE")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_library_id ON images(library_id)")
    # Backfill: any image without library_id gets one based on its parent directory.
    orphans = conn.execute(
        "SELECT id, path FROM images WHERE library_id IS NULL"
    ).fetchall()
    if not orphans:
        return
    from datetime import datetime as _dt, timezone as _tz
    by_root: dict[str, list[int]] = {}
    for r in orphans:
        root = str(Path(r["path"]).parent)
        by_root.setdefault(root, []).append(int(r["id"]))
    now = _dt.now(_tz.utc).isoformat()
    for root, ids in by_root.items():
        conn.execute(
            "INSERT OR IGNORE INTO libraries(root_path, display_name, added_at) VALUES (?, ?, ?)",
            (root, Path(root).name or root, now),
        )
        lib = conn.execute("SELECT id FROM libraries WHERE root_path=?", (root,)).fetchone()
        if not lib:
            continue
        lib_id = int(lib["id"])
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE images SET library_id=? WHERE id IN ({placeholders})",
            [lib_id, *ids],
        )


def ensure_library(conn: sqlite3.Connection, root_path: str, display_name: str | None = None) -> int:
    from datetime import datetime as _dt, timezone as _tz
    row = conn.execute("SELECT id FROM libraries WHERE root_path=?", (root_path,)).fetchone()
    if row:
        return int(row["id"])
    conn.execute(
        "INSERT INTO libraries(root_path, display_name, added_at, models_run, models_pending) "
        "VALUES (?, ?, ?, ?, ?)",
        (root_path, display_name or Path(root_path).name or root_path, _dt.now(_tz.utc).isoformat(), "{}", "[]"),
    )
    row = conn.execute("SELECT id FROM libraries WHERE root_path=?", (root_path,)).fetchone()
    return int(row["id"])


def list_libraries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT l.id, l.root_path, l.display_name, l.added_at, l.models_run, l.models_pending, "
        "  (SELECT COUNT(*) FROM images i WHERE i.library_id = l.id) AS image_count "
        "FROM libraries l ORDER BY l.added_at DESC, l.id DESC"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        lib_id = int(r["id"])
        verdict_rows = conn.execute(
            "SELECT v.verdict, COUNT(*) AS c FROM verdicts v "
            "JOIN images i ON i.id = v.image_id WHERE i.library_id = ? GROUP BY v.verdict",
            (lib_id,),
        ).fetchall()
        by_verdict = {vr["verdict"]: int(vr["c"]) for vr in verdict_rows}
        out.append(
            {
                "id": lib_id,
                "root_path": r["root_path"],
                "display_name": r["display_name"],
                "added_at": r["added_at"],
                "image_count": int(r["image_count"]),
                "by_verdict": by_verdict,
                "models_run": json.loads(r["models_run"]) if r["models_run"] else {},
                "models_pending": json.loads(r["models_pending"]) if r["models_pending"] else [],
            }
        )
    return out


def delete_library(conn: sqlite3.Connection, library_id: int) -> dict[str, int]:
    counts = {
        "images": int(conn.execute("SELECT COUNT(*) AS c FROM images WHERE library_id=?", (library_id,)).fetchone()["c"]),
    }
    with transaction(conn):
        conn.execute("DELETE FROM images WHERE library_id=?", (library_id,))
        conn.execute("DELETE FROM libraries WHERE id=?", (library_id,))
    cleanup_orphan_bursts(conn)
    return counts


def set_burst_best(conn: sqlite3.Connection, burst_id: int, image_id: int) -> bool:
    """Mark `image_id` as the best pick of `burst_id`. Returns False if the image
    isn't a member of the burst. Only moves the `is_best` flag — verdicts are the
    user's call here (unlike the auto-demotion group_bursts does on regroup)."""
    member = conn.execute(
        "SELECT 1 FROM burst_members WHERE burst_id=? AND image_id=?",
        (burst_id, image_id),
    ).fetchone()
    if not member:
        return False
    with transaction(conn):
        conn.execute("UPDATE burst_members SET is_best=0 WHERE burst_id=?", (burst_id,))
        conn.execute(
            "UPDATE burst_members SET is_best=1 WHERE burst_id=? AND image_id=?",
            (burst_id, image_id),
        )
    return True


def cleanup_orphan_bursts(conn: sqlite3.Connection) -> int:
    """Drop bursts whose members were all removed (e.g. by cascading image deletes).

    The burst_members FK cascades on image delete, so empty bursts are left
    behind. This sweeps them out and returns the count removed.
    """
    cur = conn.execute(
        "DELETE FROM bursts WHERE id NOT IN (SELECT DISTINCT burst_id FROM burst_members)"
    )
    return cur.rowcount or 0


def set_library_models(
    conn: sqlite3.Connection,
    library_id: int,
    models_run: dict[str, str] | None = None,
    models_pending: list[str] | None = None,
) -> None:
    row = conn.execute(
        "SELECT models_run, models_pending FROM libraries WHERE id=?", (library_id,)
    ).fetchone()
    if not row:
        return
    cur_run = json.loads(row["models_run"]) if row["models_run"] else {}
    cur_pending = json.loads(row["models_pending"]) if row["models_pending"] else []
    if models_run is not None:
        cur_run.update(models_run)
    if models_pending is not None:
        cur_pending = list(models_pending)
    conn.execute(
        "UPDATE libraries SET models_run=?, models_pending=? WHERE id=?",
        (json.dumps(cur_run), json.dumps(cur_pending), library_id),
    )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def upsert_image(conn: sqlite3.Connection, fields: dict[str, Any]) -> int:
    cols = list(fields.keys())
    placeholders = ",".join("?" for _ in cols)
    setters = ",".join(f"{c}=excluded.{c}" for c in cols if c != "path")
    sql = (
        f"INSERT INTO images ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(path) DO UPDATE SET {setters}"
    )
    conn.execute(sql, [fields[c] for c in cols])
    row = conn.execute("SELECT id FROM images WHERE path=?", (fields["path"],)).fetchone()
    return int(row["id"])


def save_metrics(conn: sqlite3.Connection, image_id: int, metrics: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO metrics(image_id, json) VALUES(?, ?) "
        "ON CONFLICT(image_id) DO UPDATE SET json=excluded.json",
        (image_id, json.dumps(metrics, default=str)),
    )


def save_embedding(
    conn: sqlite3.Connection, image_id: int, model: str, vec: bytes, dim: int,
) -> None:
    conn.execute(
        "INSERT INTO image_embeddings(image_id, model, dim, embedding) VALUES(?,?,?,?) "
        "ON CONFLICT(image_id) DO UPDATE SET "
        "  model=excluded.model, dim=excluded.dim, embedding=excluded.embedding",
        (image_id, model, dim, vec),
    )


def save_verdict(
    conn: sqlite3.Connection,
    image_id: int,
    verdict: str,
    stars: int,
    label: str | None,
    reasons: list[str],
) -> None:
    conn.execute(
        "INSERT INTO verdicts(image_id, verdict, stars, label, reasons) VALUES(?,?,?,?,?) "
        "ON CONFLICT(image_id) DO UPDATE SET "
        "  verdict=excluded.verdict, stars=excluded.stars, "
        "  label=excluded.label, reasons=excluded.reasons "
        "WHERE user_override=0",
        (image_id, verdict, stars, label, json.dumps(reasons)),
    )


def needs_analysis(conn: sqlite3.Connection, path: str, mtime: float) -> bool:
    row = conn.execute(
        "SELECT mtime, analyzed_at FROM images WHERE path=?", (path,)
    ).fetchone()
    if not row:
        return True
    if row["analyzed_at"] is None:
        return True
    return float(row["mtime"]) != float(mtime)


def fetch_verdicts(conn: sqlite3.Connection, paths: list[str] | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT i.path, i.capture_time, i.camera_model, v.verdict, v.stars, v.label, v.reasons "
        "FROM images i JOIN verdicts v ON v.image_id = i.id"
    )
    params: tuple = ()
    if paths:
        placeholders = ",".join("?" for _ in paths)
        sql += f" WHERE i.path IN ({placeholders})"
        params = tuple(paths)
    sql += " ORDER BY i.path"
    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "path": r["path"],
                "capture_time": r["capture_time"],
                "camera_model": r["camera_model"],
                "verdict": r["verdict"],
                "stars": r["stars"],
                "label": r["label"],
                "reasons": json.loads(r["reasons"]) if r["reasons"] else [],
            }
        )
    return out
