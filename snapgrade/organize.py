"""Token-based hierarchical organizer.

Each token is a pure function `(record) -> str` (or "/"-joined path for tokens
that imply nested levels, e.g. date:YYYY/MM). The user supplies an ordered
list of tokens; the engine builds:

    <root> / token1(rec) / token2(rec) / ... / <filename>

Default operation is symlink (non-destructive). A 'commit' converts symlinks
to moves. Conflicts get a stable short hash of the source path appended.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


Record = dict[str, Any]
Token = Callable[[Record], str]


def _safe(s: str | None) -> str:
    if not s:
        return "_unknown"
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in s.strip())
    return cleaned or "_unknown"


def _parse_dt(rec: Record) -> datetime | None:
    s = rec.get("capture_time")
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _date_token(fmt: str) -> Token:
    def f(rec: Record) -> str:
        dt = _parse_dt(rec)
        return dt.strftime(fmt) if dt else "_undated"
    return f


def _camera_make(rec: Record) -> str:
    return _safe(rec.get("camera_make"))


def _camera_model(rec: Record) -> str:
    return _safe(rec.get("camera_model"))


def _camera_make_model(rec: Record) -> str:
    parts = [p for p in (rec.get("camera_make"), rec.get("camera_model")) if p]
    return _safe(" ".join(parts)) if parts else "_unknown"


def _lens_model(rec: Record) -> str:
    return _safe(rec.get("lens_model"))


def _focal_bucket(rec: Record) -> str:
    f = rec.get("focal_length_mm")
    if f is None:
        return "_unknown"
    f = float(f)
    if f < 16:
        return "ultrawide"
    if f < 35:
        return "wide"
    if f < 70:
        return "standard"
    if f < 135:
        return "short-tele"
    if f < 300:
        return "tele"
    return "super-tele"


def _orientation(rec: Record) -> str:
    w, h = rec.get("width") or 0, rec.get("height") or 0
    if not w or not h:
        return "_unknown"
    if abs(w - h) <= max(w, h) * 0.02:
        return "square"
    return "landscape" if w > h else "portrait"


def _iso_bucket(rec: Record) -> str:
    iso = rec.get("iso")
    if not iso:
        return "_unknown"
    iso = int(iso)
    if iso <= 200:
        return "iso-low"
    if iso <= 1600:
        return "iso-mid"
    if iso <= 6400:
        return "iso-high"
    return "iso-extreme"


def _flash(rec: Record) -> str:
    metrics = rec.get("_metrics", {})
    f = metrics.get("flash_fired") if isinstance(metrics, dict) else None
    if f is True:
        return "flash-on"
    if f is False:
        return "flash-off"
    return "_unknown"


def _verdict(rec: Record) -> str:
    return _safe(rec.get("verdict"))


def _stars(rec: Record) -> str:
    s = rec.get("stars")
    return f"{int(s)}-star" if s else "_unknown"


def _gps_country(rec: Record) -> str:
    from . import geocode

    place = geocode.lookup(rec.get("gps_lat"), rec.get("gps_lon"))
    return _safe(place.country) if place.country else "_unknown"


def _gps_city(rec: Record) -> str:
    from . import geocode

    place = geocode.lookup(rec.get("gps_lat"), rec.get("gps_lon"))
    return _safe(place.city) if place.city else "_unknown"


def _event(rec: Record) -> str:
    label = rec.get("event_label")
    return _safe(label) if label else "_unknown"


def _scene(rec: Record) -> str:
    metrics = rec.get("_metrics", {})
    s = metrics.get("scene") if isinstance(metrics, dict) else None
    if isinstance(s, dict) and s.get("primary"):
        return _safe(str(s["primary"]))
    return "_unknown"


def _object_class(rec: Record) -> str:
    metrics = rec.get("_metrics", {})
    o = metrics.get("objects") if isinstance(metrics, dict) else None
    if isinstance(o, dict) and o.get("primary"):
        return _safe(str(o["primary"]))
    return "_unknown"


def _content_type(rec: Record) -> str:
    metrics = rec.get("_metrics", {})
    # "content_type" is the current key; "screendoc" kept for old DB rows.
    ct = None
    if isinstance(metrics, dict):
        ct = metrics.get("content_type") or metrics.get("screendoc")
    if isinstance(ct, dict) and ct.get("class"):
        return _safe(str(ct["class"]))
    return "_unknown"


TOKENS: dict[str, Token] = {
    "date:YYYY": _date_token("%Y"),
    "date:YYYY-MM": _date_token("%Y-%m"),
    "date:YYYY-MM-DD": _date_token("%Y-%m-%d"),
    "date:YYYY/MM": _date_token("%Y/%m"),
    "date:YYYY/MM/DD": _date_token("%Y/%m/%d"),
    "camera:make": _camera_make,
    "camera:model": _camera_model,
    "camera:make_model": _camera_make_model,
    "lens:model": _lens_model,
    "focal_bucket": _focal_bucket,
    "orientation": _orientation,
    "iso_bucket": _iso_bucket,
    "flash": _flash,
    "quality:verdict": _verdict,
    "quality:stars": _stars,
    "gps:country": _gps_country,
    "gps:city": _gps_city,
    "event": _event,
    "scene": _scene,
    "object:class": _object_class,
    "content_type": _content_type,
}


def list_tokens() -> list[str]:
    return list(TOKENS.keys())


@dataclass(frozen=True)
class PlanEntry:
    source: Path
    target: Path


@dataclass(frozen=True)
class OrganizePlan:
    entries: tuple[PlanEntry, ...]
    conflicts: int

    def summary(self) -> str:
        return f"{len(self.entries)} files → tree; {self.conflicts} name conflicts auto-suffixed"


def _records_for_paths(conn: sqlite3.Connection, paths: list[str] | None) -> list[Record]:
    sql = (
        "SELECT i.id, i.path, i.capture_time, i.camera_make, i.camera_model, i.lens_model, "
        "i.focal_length_mm, i.iso, i.f_number, i.width, i.height, i.gps_lat, i.gps_lon, "
        "v.verdict, v.stars, v.label, m.json AS metrics_json, e.label AS event_label "
        "FROM images i "
        "LEFT JOIN verdicts v ON v.image_id = i.id "
        "LEFT JOIN metrics m ON m.image_id = i.id "
        "LEFT JOIN event_members em ON em.image_id = i.id "
        "LEFT JOIN events e ON e.id = em.event_id"
    )
    params: tuple = ()
    if paths:
        placeholders = ",".join("?" for _ in paths)
        sql += f" WHERE i.path IN ({placeholders})"
        params = tuple(paths)
    rows = conn.execute(sql, params).fetchall()
    out: list[Record] = []
    for r in rows:
        rec = {k: r[k] for k in r.keys() if k != "metrics_json"}
        rec["_metrics"] = json.loads(r["metrics_json"]) if r["metrics_json"] else {}
        out.append(rec)
    return out


def _disambiguate(target: Path, source: Path, taken: set[Path]) -> tuple[Path, bool]:
    if target not in taken and not target.exists():
        return target, False
    h = hashlib.sha1(str(source).encode()).hexdigest()[:6]
    new_target = target.with_name(f"{target.stem}__{h}{target.suffix}")
    return new_target, True


def build_plan(
    conn: sqlite3.Connection,
    root: Path,
    token_names: list[str],
    paths: list[str] | None = None,
) -> OrganizePlan:
    tokens: list[Token] = []
    for name in token_names:
        if name not in TOKENS:
            raise ValueError(f"Unknown organize token: {name}")
        tokens.append(TOKENS[name])

    entries: list[PlanEntry] = []
    taken: set[Path] = set()
    conflicts = 0
    for rec in _records_for_paths(conn, paths):
        src = Path(rec["path"])
        parts: list[str] = []
        for tok in tokens:
            value = tok(rec)
            parts.extend(p for p in value.split("/") if p)
        dest_dir = root.joinpath(*parts) if parts else root
        target = dest_dir / src.name
        target, bumped = _disambiguate(target, src, taken)
        if bumped:
            conflicts += 1
        taken.add(target)
        entries.append(PlanEntry(source=src, target=target))
    return OrganizePlan(entries=tuple(entries), conflicts=conflicts)


def apply_plan(
    plan: OrganizePlan,
    mode: str = "symlink",
    dry_run: bool = True,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Materialise an organize plan and, when files move on disk, update the DB.

    When `mode == "move"`, the source path in the DB is rewritten to the new
    target so subsequent thumbnail / preview lookups stay valid without a
    full re-ingest. Symlink/hardlink/copy leave the source intact, so the DB
    needs no path changes.
    """
    if mode not in {"symlink", "hardlink", "move", "copy"}:
        raise ValueError(f"Unknown mode: {mode}")
    written = 0
    moves: list[tuple[str, str]] = []
    for entry in plan.entries:
        if dry_run:
            written += 1
            continue
        entry.target.parent.mkdir(parents=True, exist_ok=True)
        if entry.target.exists() or entry.target.is_symlink():
            continue
        if mode == "symlink":
            entry.target.symlink_to(entry.source)
        elif mode == "hardlink":
            try:
                entry.target.hardlink_to(entry.source)
            except OSError:
                shutil.copy2(entry.source, entry.target)
        elif mode == "move":
            shutil.move(str(entry.source), str(entry.target))
            moves.append((str(entry.source), str(entry.target)))
        elif mode == "copy":
            shutil.copy2(entry.source, entry.target)
        written += 1

    if conn is not None and moves and not dry_run:
        for src, dst in moves:
            conn.execute("UPDATE images SET path=? WHERE path=?", (dst, src))
    return written
