"""Burst / near-duplicate grouping with best-of-burst selection."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import db
from .metrics.phash import hamming


@dataclass(frozen=True)
class BurstConfig:
    hamming_threshold: int = 10          # bits-of-difference cutoff on 64-bit phash
    time_window_seconds: int = 3         # capture-time proximity required
    w_sharpness: float = 0.50
    w_eyes: float = 0.20
    w_exposure: float = 0.15
    w_aesthetic: float = 0.15


@dataclass(frozen=True)
class Burst:
    burst_id: int
    image_ids: tuple[int, ...]
    best_image_id: int


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


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _quality_score(metrics: dict, cfg: BurstConfig) -> float:
    sharp = (metrics.get("subject_sharpness") or metrics.get("sharpness") or {}).get("score", 0.0)
    eyes = metrics.get("eyes") or {}
    expo = metrics.get("exposure") or {}
    eye_score = 0.0 if eyes.get("any_closed") else 1.0
    expo_score = 0.0 if (expo.get("overexposed") or expo.get("underexposed")) else 1.0
    aesthetic = metrics.get("aesthetic_score", 0.5) or 0.5
    return (
        cfg.w_sharpness * sharp
        + cfg.w_eyes * eye_score
        + cfg.w_exposure * expo_score
        + cfg.w_aesthetic * aesthetic
    )


def _load_candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT i.id, i.capture_time, i.phash, m.json AS metrics_json "
        "FROM images i JOIN metrics m ON m.image_id = i.id "
        "WHERE i.phash IS NOT NULL "
        "ORDER BY i.capture_time NULLS LAST, i.id"
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "id": int(r["id"]),
                "time": _parse_time(r["capture_time"]),
                "phash": r["phash"],
                "metrics": json.loads(r["metrics_json"]) if r["metrics_json"] else {},
            }
        )
    return out


def group_bursts(conn: sqlite3.Connection, cfg: BurstConfig | None = None) -> list[Burst]:
    cfg = cfg or BurstConfig()
    items = _load_candidates(conn)
    n = len(items)
    if n == 0:
        return []

    uf = _UnionFind(n)
    window = timedelta(seconds=cfg.time_window_seconds)

    # Only pair-check within a sliding capture-time window. Items without a
    # capture time fall through (they only merge with each other on phash).
    for i, a in enumerate(items):
        for j in range(i + 1, n):
            b = items[j]
            if a["time"] and b["time"]:
                if b["time"] - a["time"] > window:
                    break
            elif a["time"] or b["time"]:
                continue
            if hamming(a["phash"], b["phash"]) <= cfg.hamming_threshold:
                uf.union(i, j)

    clusters: dict[int, list[int]] = {}
    for idx in range(n):
        clusters.setdefault(uf.find(idx), []).append(idx)

    bursts: list[Burst] = []
    with db.transaction(conn):
        conn.execute("DELETE FROM burst_members")
        conn.execute("DELETE FROM bursts")
        for member_idxs in clusters.values():
            if len(member_idxs) < 2:
                continue
            scored = [
                (idx, _quality_score(items[idx]["metrics"], cfg)) for idx in member_idxs
            ]
            scored.sort(key=lambda t: t[1], reverse=True)
            best_idx = scored[0][0]
            cur = conn.execute(
                "INSERT INTO bursts(created_at) VALUES(?)",
                (datetime.utcnow().isoformat(),),
            )
            burst_id = int(cur.lastrowid)
            image_ids = tuple(items[idx]["id"] for idx in member_idxs)
            for idx in member_idxs:
                conn.execute(
                    "INSERT INTO burst_members(burst_id, image_id, is_best) VALUES(?,?,?)",
                    (burst_id, items[idx]["id"], 1 if idx == best_idx else 0),
                )
            # Demote non-best burst members from keeper → review.
            non_best = [items[idx]["id"] for idx in member_idxs if idx != best_idx]
            if non_best:
                placeholders = ",".join("?" for _ in non_best)
                conn.execute(
                    f"UPDATE verdicts SET verdict='review', label='yellow' "
                    f"WHERE user_override=0 AND verdict='keeper' AND image_id IN ({placeholders})",
                    non_best,
                )
            bursts.append(
                Burst(
                    burst_id=burst_id,
                    image_ids=image_ids,
                    best_image_id=items[best_idx]["id"],
                )
            )
    return bursts
