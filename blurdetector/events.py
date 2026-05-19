"""Time-gap event clustering — splits a library into 'events' wherever the
capture-time gap exceeds a threshold (default 6 hours).

Events are persisted into a separate table so the organizer can use them as a
token (`event` → `event-0042`) without recomputing on every run.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from . import db


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def build(conn: sqlite3.Connection, gap_hours: float = 6.0) -> int:
    rows = conn.execute(
        "SELECT id, capture_time FROM images WHERE capture_time IS NOT NULL "
        "ORDER BY capture_time, id"
    ).fetchall()
    if not rows:
        return 0
    gap = timedelta(hours=gap_hours)
    events: list[list[tuple[int, datetime]]] = []
    current: list[tuple[int, datetime]] = []
    prev: datetime | None = None
    for r in rows:
        t = _parse(r["capture_time"])
        if t is None:
            continue
        if prev is not None and (t - prev) > gap:
            if current:
                events.append(current)
            current = []
        current.append((int(r["id"]), t))
        prev = t
    if current:
        events.append(current)

    with db.transaction(conn):
        conn.execute("DELETE FROM event_members")
        conn.execute("DELETE FROM events")
        for idx, members in enumerate(events):
            start = members[0][1].isoformat()
            end = members[-1][1].isoformat()
            label = f"event-{idx:04d}"
            cur = conn.execute(
                "INSERT INTO events(label, start_time, end_time) VALUES(?,?,?)",
                (label, start, end),
            )
            eid = int(cur.lastrowid)
            for img_id, _ in members:
                conn.execute(
                    "INSERT INTO event_members(event_id, image_id) VALUES(?,?)",
                    (eid, img_id),
                )
    return len(events)


def event_label_for(conn: sqlite3.Connection, image_id: int) -> str | None:
    row = conn.execute(
        "SELECT e.label FROM events e JOIN event_members m ON m.event_id = e.id "
        "WHERE m.image_id = ?",
        (image_id,),
    ).fetchone()
    return row["label"] if row else None
