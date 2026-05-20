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
    total_row = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()
    total = total_row["c"] if total_row else 0
    by_verdict = conn.execute(
        "SELECT verdict, COUNT(*) AS c FROM verdicts GROUP BY verdict"
    ).fetchall()
    bursts = conn.execute(
        "SELECT COUNT(*) AS c FROM bursts b "
        "WHERE EXISTS(SELECT 1 FROM burst_members bm WHERE bm.burst_id = b.id)"
    ).fetchone()["c"]
    libraries_count = int(conn.execute("SELECT COUNT(*) AS c FROM libraries").fetchone()["c"])

    return {
        "images": int(total),
        "folders": libraries_count,
        "libraries": libraries_count,
        "by_verdict": {r["verdict"]: int(r["c"]) for r in by_verdict},
        "bursts": int(bursts),
        "ingest": INGEST_STATE,
    }


@app.post("/api/select_folder")
def select_folder() -> dict[str, str | None]:
    """macOS folder picker; AppleScript is forced to the front via System Events."""
    import subprocess
    script = (
        'tell application "System Events" to activate\n'
        'try\n'
        '  set chosen to choose folder with prompt "Select photo folder"\n'
        '  return POSIX path of chosen\n'
        'on error number -128\n'
        '  return ""\n'
        'end try'
    )
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True)
        path = res.stdout.strip()
        return {"path": path or None}
    except subprocess.CalledProcessError:
        return {"path": None}
    except FileNotFoundError:
        raise HTTPException(501, "Folder picker requires macOS (osascript)")
    except Exception as e:
        raise HTTPException(500, f"Failed to run dialog: {e}")


@app.get("/api/libraries")
def list_libraries_endpoint() -> dict[str, Any]:
    conn = _conn()
    items = db.list_libraries(conn)
    return {"items": items, "available_models": _available_models()}


@app.post("/api/libraries/{library_id}/sync")
def sync_library(library_id: int, background: BackgroundTasks) -> dict[str, Any]:
    """Reconcile a library with disk: add new files, drop missing files, re-run the
    same model set that was previously applied to the library."""
    conn = _conn()
    row = conn.execute(
        "SELECT root_path, models_run FROM libraries WHERE id=?", (library_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "library not found")
    if INGEST_STATE["running"]:
        raise HTTPException(409, "ingest already running")
    root = Path(row["root_path"])
    if not root.is_dir():
        raise HTTPException(410, f"library root no longer exists: {root}")
    models_run = json.loads(row["models_run"] or "{}")
    model_list = list(models_run.keys())

    # Drop DB rows whose files no longer exist on disk.
    existing = {str(p) for p in pipeline.walk_images(root)}
    catalogued = conn.execute(
        "SELECT id, path FROM images WHERE library_id=?", (library_id,)
    ).fetchall()
    to_drop = [int(r["id"]) for r in catalogued if r["path"] not in existing]
    if to_drop:
        placeholders = ",".join("?" for _ in to_drop)
        conn.execute(f"DELETE FROM images WHERE id IN ({placeholders})", to_drop)
        db.cleanup_orphan_bursts(conn)

    def _run() -> None:
        total = _count_supported_files(root)
        INGEST_STATE.update(running=True, folder=str(root), done=0, total=total, error=None)
        try:
            for _ in pipeline.analyze_folder(root, models=model_list, library_id=library_id):
                INGEST_STATE["done"] += 1
        except Exception as e:
            INGEST_STATE["error"] = str(e)
        finally:
            INGEST_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "removed": len(to_drop), "models": model_list}


@app.delete("/api/libraries/{library_id}")
def remove_library(library_id: int) -> dict[str, Any]:
    conn = _conn()
    counts = db.delete_library(conn, library_id)
    return {"removed": counts}


class RunModelsRequest(BaseModel):
    models: list[str]


@app.post("/api/libraries/{library_id}/run_models")
def run_library_models(library_id: int, req: RunModelsRequest, background: BackgroundTasks) -> dict[str, Any]:
    conn = _conn()
    row = conn.execute("SELECT root_path FROM libraries WHERE id=?", (library_id,)).fetchone()
    if not row:
        raise HTTPException(404, "library not found")
    if INGEST_STATE["running"]:
        raise HTTPException(409, "ingest already running")
    root = Path(row["root_path"])
    models = [m for m in req.models if m in _AVAILABLE_MODEL_NAMES]

    db.set_library_models(conn, library_id, models_pending=models)

    def _run() -> None:
        total = _count_supported_files(root)
        INGEST_STATE.update(running=True, folder=str(root), done=0, total=total, error=None)
        try:
            for _ in pipeline.analyze_folder(root, models=models, library_id=library_id, force=True):
                INGEST_STATE["done"] += 1
            from datetime import datetime as _dt
            bg_conn = _conn()
            now = _dt.utcnow().isoformat()
            db.set_library_models(
                bg_conn, library_id,
                models_run={m: now for m in models},
                models_pending=[],
            )
        except Exception as e:
            INGEST_STATE["error"] = str(e)
        finally:
            INGEST_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "models": models}


_AVAILABLE_MODEL_NAMES = ("scene", "subject_seg", "objects", "screendoc")

# Best-effort public URLs for small model weights. None means "no known public
# source"; the user can supply one via the `url` query param to /download.
MODEL_DOWNLOAD_URLS: dict[str, dict[str, str]] = {
    "subject_seg": {
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
        "filename": "u2netp.onnx",
    },
    "objects": {
        "url": "https://huggingface.co/Xenova/yolov8n/resolve/main/onnx/model.onnx",
        "filename": "yolov8n.onnx",
    },
    "scene": {
        "url": "",  # Places365 CoreML / ONNX not reliably hosted; user must supply.
        "filename": "places365.mlpackage",
    },
    "screendoc": {
        "url": "",  # No reliable public model; heuristic fallback ships in-tree.
        "filename": "screendoc.mlpackage",
    },
}

DOWNLOAD_STATE: dict[str, Any] = {"running": False, "model": None, "downloaded": 0, "total": None, "error": None}


def _available_models() -> list[dict[str, Any]]:
    """Probe each optional model module for availability."""
    out: list[dict[str, Any]] = []
    for name in _AVAILABLE_MODEL_NAMES:
        try:
            mod = __import__(f"blurdetector.metrics.{name}", fromlist=["is_available"])
            avail = bool(mod.is_available())
        except Exception:
            avail = False
        out.append({"name": name, "available": avail})
    return out


@app.get("/api/models")
def list_available_models() -> dict[str, Any]:
    out = []
    for m in _available_models():
        info = MODEL_DOWNLOAD_URLS.get(m["name"], {})
        out.append({
            **m,
            "download_url": info.get("url", ""),
            "filename": info.get("filename", ""),
        })
    return {"models": out, "download_state": DOWNLOAD_STATE}


@app.post("/api/models/{name}/download")
def download_model(name: str, background: BackgroundTasks, url: str | None = Query(None)) -> dict[str, Any]:
    if name not in _AVAILABLE_MODEL_NAMES:
        raise HTTPException(404, f"unknown model: {name}")
    info = MODEL_DOWNLOAD_URLS.get(name, {})
    fetch_url = url or info.get("url", "")
    filename = info.get("filename", f"{name}.bin")
    if not fetch_url:
        raise HTTPException(
            400,
            f"No public URL is registered for '{name}'. Pass ?url=... to specify one, "
            f"or drop the weights at ~/.blurdetector/models/{filename} manually.",
        )
    if DOWNLOAD_STATE["running"]:
        raise HTTPException(409, "another model download is in progress")
    dest = Path.home() / ".blurdetector" / "models" / filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> None:
        import urllib.request
        DOWNLOAD_STATE.update(running=True, model=name, downloaded=0, total=None, error=None)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            def hook(blocks: int, block_size: int, total: int) -> None:
                DOWNLOAD_STATE["downloaded"] = blocks * block_size
                if total > 0:
                    DOWNLOAD_STATE["total"] = total
            req = urllib.request.Request(fetch_url, headers={"User-Agent": "BlurDetector/0.1"})
            with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                if total:
                    DOWNLOAD_STATE["total"] = total
                buf = 1 << 15
                while True:
                    chunk = resp.read(buf)
                    if not chunk:
                        break
                    f.write(chunk)
                    DOWNLOAD_STATE["downloaded"] += len(chunk)
            tmp.replace(dest)
        except Exception as e:
            DOWNLOAD_STATE["error"] = str(e)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        finally:
            DOWNLOAD_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "model": name, "url": fetch_url, "dest": str(dest)}


@app.get("/api/folders")
def list_folders() -> dict[str, Any]:
    """Back-compat: returns library root paths (formerly derived from image parents)."""
    conn = _conn()
    rows = conn.execute("SELECT root_path FROM libraries ORDER BY root_path").fetchall()
    return {"folders": [r["root_path"] for r in rows]}


@app.get("/api/images")
def list_images(
    verdict: str | None = Query(None),
    burst: int | None = Query(None),
    folder: str | None = Query(None),
    library_id: int | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    conn = _conn()
    sql = (
        "SELECT i.id, i.path, i.capture_time, i.camera_model, i.iso, i.f_number, "
        "i.width, i.height, i.content_hash, i.library_id, "
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
    if library_id is not None:
        where.append("i.library_id = ?")
        params.append(library_id)
    if folder:
        where.append("i.path LIKE ?")
        params.append(f"{folder}/%")
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
                "library_id": int(r["library_id"]) if r["library_id"] is not None else None,
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


def _count_supported_files(root: Path) -> int:
    from . import decode
    n = 0
    for p in root.rglob("*"):
        if p.is_file() and decode.is_supported(p):
            n += 1
    return n


@app.post("/api/ingest")
def ingest(
    background: BackgroundTasks,
    folder: str = Query("", description="Folder path to ingest (required, non-empty)"),
    models: str = Query("", description="Comma-separated model names to run"),
) -> dict[str, Any]:
    if not folder or not folder.strip():
        raise HTTPException(400, "folder required")
    folder_path = Path(folder.strip()).expanduser().resolve()
    if not folder_path.is_dir():
        raise HTTPException(400, "folder does not exist")
    if INGEST_STATE["running"]:
        raise HTTPException(409, "ingest already running")
    model_list = [m.strip() for m in models.split(",") if m.strip() in _AVAILABLE_MODEL_NAMES]

    conn = _conn()
    library_id = db.ensure_library(conn, str(folder_path))
    if model_list:
        db.set_library_models(conn, library_id, models_pending=model_list)

    def _run() -> None:
        total = _count_supported_files(folder_path)
        INGEST_STATE.update(running=True, folder=str(folder_path), done=0, total=total, error=None)
        try:
            for _ in pipeline.analyze_folder(folder_path, models=model_list, library_id=library_id):
                INGEST_STATE["done"] += 1
            if model_list:
                from datetime import datetime as _dt
                bg_conn = _conn()
                now = _dt.utcnow().isoformat()
                db.set_library_models(
                    bg_conn, library_id,
                    models_run={m: now for m in model_list},
                    models_pending=[],
                )
        except Exception as e:
            INGEST_STATE["error"] = str(e)
        finally:
            INGEST_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "folder": str(folder_path), "library_id": library_id, "models": model_list}


@app.post("/api/group")
def regroup(hamming: int = 10, seconds: int = 3) -> dict[str, Any]:
    conn = _conn()
    bursts = group.group_bursts(
        conn, group.BurstConfig(hamming_threshold=hamming, time_window_seconds=seconds)
    )
    db.cleanup_orphan_bursts(conn)
    return {"bursts": len(bursts)}


@app.get("/api/bursts")
def list_bursts(library_id: int | None = Query(None)) -> dict[str, Any]:
    conn = _conn()
    if library_id is None:
        rows = conn.execute(
            "SELECT b.id AS burst_id, COUNT(bm.image_id) AS n "
            "FROM bursts b JOIN burst_members bm ON bm.burst_id = b.id "
            "GROUP BY b.id HAVING n > 0 ORDER BY b.id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT b.id AS burst_id, COUNT(bm.image_id) AS n "
            "FROM bursts b JOIN burst_members bm ON bm.burst_id = b.id "
            "JOIN images i ON i.id = bm.image_id "
            "WHERE i.library_id = ? "
            "GROUP BY b.id HAVING n > 0 ORDER BY b.id",
            (library_id,),
        ).fetchall()
    return {"items": [{"burst_id": int(r["burst_id"]), "count": int(r["n"])} for r in rows]}


@app.get("/api/tokens")
def tokens() -> dict[str, Any]:
    return {"tokens": organize.list_tokens()}


class OrganizeRequest(BaseModel):
    root: str | None = None
    levels: list[str]
    mode: str = "symlink"
    apply: bool = False
    scope: str | None = None
    library_id: int | None = None
    in_place: bool = False
    confirm: str | None = None  # required when in_place=True with apply=True


@app.post("/api/organize")
def organize_endpoint(req: OrganizeRequest) -> dict[str, Any]:
    conn = _conn()
    paths: list[str] | None = None

    # Resolve scope. library_id wins over scope string.
    scope_root: Path | None = None
    if req.library_id is not None:
        row = conn.execute("SELECT root_path, display_name FROM libraries WHERE id=?", (req.library_id,)).fetchone()
        if not row:
            raise HTTPException(404, "library not found")
        scope_root = Path(row["root_path"]).expanduser().resolve()
        lib_name = row["display_name"] or scope_root.name
    elif req.scope:
        scope_root = Path(req.scope).expanduser().resolve()
        lib_name = scope_root.name
    else:
        lib_name = None

    if scope_root:
        paths = [str(p) for p in pipeline.walk_images(scope_root)]

    # Resolve destination. In-place mode reorganizes inside scope_root.
    if req.in_place:
        if scope_root is None:
            raise HTTPException(400, "in_place requires a library_id or scope")
        if req.apply and req.confirm != (lib_name or ""):
            raise HTTPException(400, "in_place apply requires `confirm` to match the library/folder name")
        target_root = scope_root
    else:
        if not req.root:
            raise HTTPException(400, "destination root required (or set in_place=true)")
        target_root = Path(req.root).expanduser().resolve()

    try:
        plan = organize.build_plan(conn, target_root, req.levels, paths)
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
