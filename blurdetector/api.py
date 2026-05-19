"""FastAPI backend.

Endpoints are deliberately thin — they just expose the SQLite cache + a few
mutators (verdict override, organize plan, threshold tweaks). The expensive
work happens in pipeline.analyze_folder, which is invoked as a background
task via /ingest.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, decide, group, organize, pipeline, thumb, xmp

UI_DIR = Path(__file__).parent.parent / "ui"
INGEST_STATE: dict[str, Any] = {"running": False, "folder": None, "done": 0, "total": None, "error": None}

app = FastAPI(title="BlurDetector", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _conn() -> sqlite3.Connection:
    return db.connect()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    by_verdict = conn.execute(
        "SELECT verdict, COUNT(*) AS c FROM verdicts GROUP BY verdict"
    ).fetchall()
    bursts = conn.execute("SELECT COUNT(*) AS c FROM bursts").fetchone()["c"]
    return {
        "images": int(total),
        "by_verdict": {r["verdict"]: int(r["c"]) for r in by_verdict},
        "bursts": int(bursts),
        "ingest": INGEST_STATE,
    }


@app.get("/api/images")
def list_images(
    verdict: str | None = Query(None),
    burst: int | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    conn = _conn()
    sql = (
        "SELECT i.id, i.path, i.capture_time, i.camera_model, i.iso, i.f_number, "
        "i.width, i.height, i.content_hash, "
        "v.verdict, v.stars, v.label, v.reasons, v.user_override, "
        "bm.burst_id, bm.is_best "
        "FROM images i "
        "LEFT JOIN verdicts v ON v.image_id = i.id "
        "LEFT JOIN burst_members bm ON bm.image_id = i.id"
    )
    where: list[str] = []
    params: list[Any] = []
    if verdict:
        where.append("v.verdict = ?")
        params.append(verdict)
    if burst is not None:
        where.append("bm.burst_id = ?")
        params.append(burst)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY i.capture_time NULLS LAST, i.id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(sql, params).fetchall()
    return {
        "items": [
            {
                "id": int(r["id"]),
                "path": r["path"],
                "capture_time": r["capture_time"],
                "camera_model": r["camera_model"],
                "iso": r["iso"],
                "f_number": r["f_number"],
                "width": r["width"],
                "height": r["height"],
                "content_hash": r["content_hash"],
                "verdict": r["verdict"],
                "stars": r["stars"],
                "label": r["label"],
                "reasons": json.loads(r["reasons"]) if r["reasons"] else [],
                "user_override": bool(r["user_override"]) if r["user_override"] is not None else False,
                "burst_id": r["burst_id"],
                "is_best": bool(r["is_best"]) if r["is_best"] is not None else False,
            }
            for r in rows
        ]
    }


@app.get("/api/images/{image_id}")
def get_image(image_id: int) -> dict[str, Any]:
    conn = _conn()
    row = conn.execute(
        "SELECT i.*, v.verdict, v.stars, v.label, v.reasons, v.user_override, m.json AS metrics_json "
        "FROM images i "
        "LEFT JOIN verdicts v ON v.image_id = i.id "
        "LEFT JOIN metrics m ON m.image_id = i.id "
        "WHERE i.id = ?",
        (image_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "image not found")
    out = {k: row[k] for k in row.keys() if k != "metrics_json"}
    out["metrics"] = json.loads(row["metrics_json"]) if row["metrics_json"] else {}
    out["reasons"] = json.loads(row["reasons"]) if row["reasons"] else []
    return out


@app.get("/api/images/{image_id}/thumb")
def get_thumb(image_id: int, size: int = Query(512, ge=64, le=2048)) -> Response:
    conn = _conn()
    row = conn.execute(
        "SELECT path, content_hash FROM images WHERE id = ?", (image_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404)
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(410, "source file missing")
    out = thumb.get_or_build(path, row["content_hash"], long_edge=size)
    return FileResponse(out, media_type="image/jpeg")


@app.get("/api/images/{image_id}/preview")
def get_preview(image_id: int) -> Response:
    conn = _conn()
    row = conn.execute("SELECT path FROM images WHERE id = ?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(410)
    data = thumb.render_to_bytes(path, long_edge=1600)
    return Response(content=data, media_type="image/jpeg")


class VerdictUpdate(BaseModel):
    verdict: str | None = None
    stars: int | None = None
    label: str | None = None


@app.post("/api/images/{image_id}/verdict")
def update_verdict(image_id: int, payload: VerdictUpdate) -> dict[str, Any]:
    conn = _conn()
    row = conn.execute(
        "SELECT verdict, stars, label, reasons FROM verdicts WHERE image_id = ?", (image_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404)
    new_verdict = payload.verdict or row["verdict"]
    new_stars = payload.stars if payload.stars is not None else row["stars"]
    new_label = payload.label if payload.label is not None else row["label"]
    conn.execute(
        "UPDATE verdicts SET verdict=?, stars=?, label=?, user_override=1 WHERE image_id=?",
        (new_verdict, new_stars, new_label, image_id),
    )
    return {"ok": True}


@app.post("/api/ingest")
def ingest(folder: str, background: BackgroundTasks) -> dict[str, Any]:
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.is_dir():
        raise HTTPException(400, "folder does not exist")
    if INGEST_STATE["running"]:
        raise HTTPException(409, "ingest already running")

    def _run() -> None:
        INGEST_STATE.update(running=True, folder=str(folder_path), done=0, total=None, error=None)
        try:
            for _ in pipeline.analyze_folder(folder_path):
                INGEST_STATE["done"] += 1
        except Exception as e:
            INGEST_STATE["error"] = str(e)
        finally:
            INGEST_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "folder": str(folder_path)}


@app.post("/api/group")
def regroup(hamming: int = 10, seconds: int = 3) -> dict[str, Any]:
    conn = _conn()
    bursts = group.group_bursts(
        conn, group.BurstConfig(hamming_threshold=hamming, time_window_seconds=seconds)
    )
    return {"bursts": len(bursts)}


@app.get("/api/bursts")
def list_bursts() -> dict[str, Any]:
    conn = _conn()
    rows = conn.execute(
        "SELECT b.id AS burst_id, COUNT(bm.image_id) AS n "
        "FROM bursts b JOIN burst_members bm ON bm.burst_id = b.id "
        "GROUP BY b.id ORDER BY b.id"
    ).fetchall()
    return {"items": [{"burst_id": int(r["burst_id"]), "count": int(r["n"])} for r in rows]}


@app.get("/api/tokens")
def tokens() -> dict[str, Any]:
    return {"tokens": organize.list_tokens()}


class OrganizeRequest(BaseModel):
    root: str
    levels: list[str]
    mode: str = "symlink"
    apply: bool = False
    scope: str | None = None


@app.post("/api/organize")
def organize_endpoint(req: OrganizeRequest) -> dict[str, Any]:
    conn = _conn()
    paths: list[str] | None = None
    if req.scope:
        scope_path = Path(req.scope).expanduser().resolve()
        paths = [str(p) for p in pipeline.walk_images(scope_path)]
    try:
        plan = organize.build_plan(conn, Path(req.root).expanduser().resolve(), req.levels, paths)
    except ValueError as e:
        raise HTTPException(400, str(e))
    written = organize.apply_plan(plan, mode=req.mode, dry_run=not req.apply)
    return {
        "plan_size": len(plan.entries),
        "conflicts": plan.conflicts,
        "written": written,
        "applied": req.apply,
        "preview": [
            {"source": str(e.source), "target": str(e.target)} for e in plan.entries[:50]
        ],
    }


class ThresholdsModel(BaseModel):
    sharp_keeper: float = 0.55
    sharp_reject: float = 0.30
    reject_closed_eyes: bool = True
    accept_overexposed: bool = False
    accept_underexposed: bool = False
    horizon_warn_deg: float = 3.0


@app.post("/api/reclassify")
def reclassify(t: ThresholdsModel) -> dict[str, Any]:
    """Re-run the decision engine using fresh thresholds against cached metrics."""
    conn = _conn()
    thresholds = decide.Thresholds(**t.model_dump())
    rows = conn.execute(
        "SELECT m.image_id, m.json FROM metrics m "
        "JOIN verdicts v ON v.image_id = m.image_id WHERE v.user_override = 0"
    ).fetchall()
    updated = 0
    with db.transaction(conn):
        for r in rows:
            metrics = json.loads(r["json"])
            v = decide.decide(metrics, thresholds)
            db.save_verdict(conn, int(r["image_id"]), v.verdict, v.stars, v.label, v.reasons)
            updated += 1
    return {"updated": updated}


@app.post("/api/images/{image_id}/xmp")
def write_xmp_endpoint(image_id: int) -> dict[str, Any]:
    conn = _conn()
    row = conn.execute(
        "SELECT i.path, v.verdict, v.stars, v.label, v.reasons "
        "FROM images i JOIN verdicts v ON v.image_id = i.id WHERE i.id = ?",
        (image_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404)
    out = xmp.write_sidecar(
        Path(row["path"]),
        rating=row["stars"],
        label=row["label"],
        verdict=row["verdict"],
        reasons=json.loads(row["reasons"]) if row["reasons"] else [],
    )
    return {"sidecar": str(out)}


# Serve the static UI last so /api/* routes win.
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
else:
    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse({"hint": "UI not built. Open the UI dir at ui/."})
