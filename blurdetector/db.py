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

DEFAULT_DB = Path.home() / ".blurdetector" / "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
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
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


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
