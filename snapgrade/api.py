"""FastAPI backend.

Endpoints are deliberately thin — they just expose the SQLite cache + a few
mutators (verdict override, organize plan, threshold tweaks). The expensive
work happens in pipeline.analyze_folder, which is invoked as a background
task via /ingest.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, decide, group, models as db_models, organize, pipeline, thumb, xmp

UI_DIR = Path(__file__).parent.parent / "ui"
INGEST_STATE: dict[str, Any] = {"running": False, "folder": None, "done": 0, "total": None, "error": None}
FACES_STATE: dict[str, Any] = {
    "running": False, "stage": None,
    "done": 0, "total": None,
    "detected": 0, "clusters": 0,
    "error": None,
}

app = FastAPI(title="SnapGrade", version="0.1.0")

# Loopback-only app: the only legitimate caller is the same-origin UI. Pinning
# CORS to the local origins (instead of "*") means a browser will refuse the
# preflight for any cross-site request, and `require_local` below forces every
# mutating route to *be* a preflighted request. Together they shut the door on a
# malicious page silently driving destructive ops (organize move, ingest) against
# 127.0.0.1 — without needing real auth for a single-user local tool.
_LOCAL_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("127.0.0.1", "localhost")
    for port in ("8765",)
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_LOCAL_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_local(x_snapgrade: str | None = Header(default=None)) -> None:
    """CSRF guard for state-changing endpoints.

    Requiring a custom header makes the request "non-simple", so the browser
    must preflight it; the locked-down CORS origin list then rejects any
    cross-site preflight. The UI sends this header on every mutation (see
    sg-data.js); a third-party page cannot.
    """
    if not x_snapgrade:
        raise HTTPException(403, "missing X-SnapGrade header (CSRF guard)")


# Serializes the single DB-writing background slot. ingest / sync / run_models /
# faces each open their own SQLite connection; running two at once trips
# "database is locked" under WAL. The lock also makes the check-and-claim atomic
# so two near-simultaneous POSTs can't both pass the running guard.
_TASK_LOCK = threading.Lock()


def _claim_db_task(state: dict[str, Any]) -> None:
    """Atomically reserve the DB-writing background slot, or raise 409."""
    with _TASK_LOCK:
        if INGEST_STATE["running"] or FACES_STATE["running"]:
            raise HTTPException(409, "a background task is already running")
        state["running"] = True


def _conn() -> sqlite3.Connection:
    return db.connect()


def _fmt_exposure(t: float | None) -> str | None:
    if t is None:
        return None
    if t >= 1.0:
        return f"{t:g}s"
    return f"1/{int(round(1.0 / t))}"


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
        "faces": FACES_STATE,
    }


@app.post("/api/select_folder", dependencies=[Depends(require_local)])
async def select_folder() -> dict[str, str | None]:
    """macOS folder picker; AppleScript is forced to the front via System Events.

    The dialog blocks until the user picks (potentially tens of seconds), so it
    runs in a threadpool rather than tying up the event loop / a worker.
    """
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

    def _run_dialog() -> dict[str, str | None]:
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

    return await run_in_threadpool(_run_dialog)


@app.get("/api/libraries")
def list_libraries_endpoint() -> dict[str, Any]:
    conn = _conn()
    items = db.list_libraries(conn)
    return {"items": items, "available_models": _available_models()}


def _reconcile_library(conn: sqlite3.Connection, library_id: int, root: Path) -> tuple[int, int]:
    """Reconcile DB paths with disk, in a single transaction. Returns (removed, rehoused).

      (a) if a file with the same content_hash is found under the root at a new
          path, update the row in place (recovers from a prior "move" organize
          that didn't propagate the rename to the DB).
      (b) otherwise drop rows whose path is gone.

    The content-hash sweep can be expensive, so this runs on the background task
    thread — never a request handler — and the mutations are wrapped so a crash
    can't leave a half-pruned library.
    """
    existing = {str(p) for p in pipeline.walk_images(root)}
    catalogued = conn.execute(
        "SELECT id, path, content_hash FROM images WHERE library_id=?", (library_id,)
    ).fetchall()
    missing = [r for r in catalogued if r["path"] not in existing]
    if not missing:
        return 0, 0

    rehoused = 0
    rehoused_ids: set[int] = set()
    catalogued_paths = {r["path"] for r in catalogued}
    unknown_disk = [p for p in existing if p not in catalogued_paths]
    with db.transaction(conn):
        if unknown_disk:
            disk_by_hash: dict[str, str] = {}
            for p in unknown_disk:
                try:
                    disk_by_hash[pipeline._content_hash(Path(p))] = p
                except Exception:
                    continue
            for r in missing:
                h = r["content_hash"]
                if h and h in disk_by_hash:
                    conn.execute("UPDATE images SET path=? WHERE id=?", (disk_by_hash[h], int(r["id"])))
                    rehoused += 1
                    rehoused_ids.add(int(r["id"]))
        still_missing = [int(r["id"]) for r in missing if int(r["id"]) not in rehoused_ids]
        if still_missing:
            placeholders = ",".join("?" for _ in still_missing)
            conn.execute(f"DELETE FROM images WHERE id IN ({placeholders})", still_missing)
    if still_missing:
        db.cleanup_orphan_bursts(conn)
    return len(still_missing), rehoused


@app.post("/api/libraries/{library_id}/sync", dependencies=[Depends(require_local)])
def sync_library(library_id: int, background: BackgroundTasks) -> dict[str, Any]:
    """Reconcile a library with disk, then re-run the same model set, in background."""
    conn = _conn()
    row = conn.execute(
        "SELECT root_path, models_run FROM libraries WHERE id=?", (library_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "library not found")
    root = Path(row["root_path"])
    if not root.is_dir():
        raise HTTPException(410, f"library root no longer exists: {root}")
    model_list = list(json.loads(row["models_run"] or "{}").keys())
    _claim_db_task(INGEST_STATE)

    def _run() -> None:
        INGEST_STATE.update(
            running=True, folder=str(root), done=0, total=None, error=None,
            removed=0, rehoused=0,
        )
        try:
            bg_conn = _conn()
            removed, rehoused = _reconcile_library(bg_conn, library_id, root)
            INGEST_STATE.update(removed=removed, rehoused=rehoused, total=_count_supported_files(root))
            for _ in pipeline.analyze_folder(root, models=model_list, library_id=library_id):
                INGEST_STATE["done"] += 1
        except Exception as e:
            INGEST_STATE["error"] = str(e)
        finally:
            INGEST_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "models": model_list}


@app.delete("/api/libraries/{library_id}", dependencies=[Depends(require_local)])
def remove_library(library_id: int) -> dict[str, Any]:
    conn = _conn()
    counts = db.delete_library(conn, library_id)
    return {"removed": counts}


class RunModelsRequest(BaseModel):
    models: list[str]


@app.post("/api/libraries/{library_id}/run_models", dependencies=[Depends(require_local)])
def run_library_models(library_id: int, req: RunModelsRequest, background: BackgroundTasks) -> dict[str, Any]:
    conn = _conn()
    row = conn.execute("SELECT root_path FROM libraries WHERE id=?", (library_id,)).fetchone()
    if not row:
        raise HTTPException(404, "library not found")
    root = Path(row["root_path"])
    models = [m for m in req.models if m in _AVAILABLE_MODEL_NAMES]

    _claim_db_task(INGEST_STATE)
    db.set_library_models(conn, library_id, models_pending=models)

    def _run() -> None:
        total = _count_supported_files(root)
        INGEST_STATE.update(running=True, folder=str(root), done=0, total=total, error=None)
        try:
            for _ in pipeline.analyze_folder(root, models=models, library_id=library_id, force=True):
                INGEST_STATE["done"] += 1
            from datetime import datetime as _dt, timezone as _tz
            bg_conn = _conn()
            now = _dt.now(_tz.utc).isoformat()
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


_AVAILABLE_MODEL_NAMES = ("scene", "subject_seg", "objects", "depth", "content_type")

# Public URLs for model weights, built from the community model host.
# The user can override per-request via the `url` query param to /download.
_REPO = db_models.MODELS_REPO_RAW
MODEL_DOWNLOAD_URLS: dict[str, dict[str, str]] = {
    "subject_seg": {"url": f"{_REPO}/u2netp.mlpackage.zip", "filename": "u2netp.mlpackage"},
    "objects": {"url": f"{_REPO}/yolo26n.mlpackage.zip", "filename": "yolo26n.mlpackage"},
    "scene": {"url": f"{_REPO}/places365.mlpackage.zip", "filename": "places365.mlpackage"},
    "depth": {"url": f"{_REPO}/depth_anything_v2_small.mlpackage.zip", "filename": "depth_anything_v2_small.mlpackage"},
    # content_type uses Apple Vision (no download); intentionally absent here.
}

DOWNLOAD_STATE: dict[str, Any] = {"running": False, "model": None, "downloaded": 0, "total": None, "error": None}


def _available_models() -> list[dict[str, Any]]:
    """Probe each optional model module for availability."""
    out: list[dict[str, Any]] = []
    for name in _AVAILABLE_MODEL_NAMES:
        try:
            mod = __import__(f"snapgrade.metrics.{name}", fromlist=["is_available"])
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


@app.post("/api/models/{name}/download", dependencies=[Depends(require_local)])
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
            f"or drop the weights at ~/.snapgrade/models/{filename} manually.",
        )
    # No DB writes here (file download only), so it may run alongside an ingest;
    # claim the download flag synchronously so two POSTs can't both pass.
    with _TASK_LOCK:
        if DOWNLOAD_STATE["running"]:
            raise HTTPException(409, "another model download is in progress")
        DOWNLOAD_STATE["running"] = True
    dest = Path.home() / ".snapgrade" / "models" / filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> None:
        import urllib.request
        import zipfile
        # macOS Python installs frequently lack a usable system CA bundle, so
        # default urllib HTTPS fails with CERTIFICATE_VERIFY_FAILED. Use
        # certifi's bundle when available (mirrors what `curl` does).
        ctx = None
        try:
            import ssl
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = None

        def _fetch(url: str, fh) -> None:
            req = urllib.request.Request(url, headers={"User-Agent": "SnapGrade/0.1"})
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                if total:
                    DOWNLOAD_STATE["total"] = total
                buf = 1 << 15
                while True:
                    chunk = resp.read(buf)
                    if not chunk:
                        break
                    fh.write(chunk)
                    DOWNLOAD_STATE["downloaded"] += len(chunk)

        DOWNLOAD_STATE.update(running=True, model=name, downloaded=0, total=None, error=None)
        is_zip = fetch_url.endswith(".zip")
        if is_zip:
            zip_dest = dest.with_suffix(dest.suffix + ".zip")
            tmp = zip_dest.with_suffix(".part")
        else:
            tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with tmp.open("wb") as f:
                _fetch(fetch_url, f)
            if is_zip:
                tmp.replace(zip_dest)
                with zipfile.ZipFile(zip_dest, "r") as zip_ref:
                    zip_ref.extractall(dest.parent)
                zip_dest.unlink()
            else:
                tmp.replace(dest)

            # Special case for scene: download places365_labels.txt too!
            if name == "scene":
                labels_dest = dest.parent / "places365_labels.txt"
                labels_tmp = labels_dest.with_suffix(".part")
                with labels_tmp.open("wb") as f:
                    _fetch(f"{_REPO}/places365_labels.txt", f)
                labels_tmp.replace(labels_dest)
        except Exception as e:
            DOWNLOAD_STATE["error"] = str(e)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            if is_zip:
                try:
                    zip_dest.unlink(missing_ok=True)
                except Exception:
                    pass
        finally:
            DOWNLOAD_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "model": name, "url": fetch_url, "dest": str(dest)}


@app.get("/api/search")
def semantic_search(
    q: str = Query(..., description="Natural-language query"),
    k: int = Query(20, ge=1, le=200),
    library_id: int | None = Query(None),
) -> dict[str, Any]:
    """Top-k images for a text query (MobileCLIP cosine ranking).

    Returns an empty list if the text model isn't installed or no embeddings
    are present yet (enable with SNAPGRADE_ENABLE_SEMANTIC=1 during analyze).
    """
    from . import search as _search
    conn = _conn()
    hits = _search.search(conn, q, k=k, library_id=library_id)
    if not hits:
        return {"items": [], "q": q}
    ids = [h[0] for h in hits]
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, path FROM images WHERE id IN ({placeholders})", ids,
    ).fetchall()
    by_id = {int(r["id"]): r for r in rows}
    items = []
    for image_id, score in hits:
        r = by_id.get(image_id)
        if not r:
            continue
        items.append({
            "image_id": image_id,
            "score": round(float(score), 4),
            "path": r["path"],
            "thumb": f"/api/images/{image_id}/thumb?size=256",
        })
    return {"items": items, "q": q}


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
    content_type: str | None = Query(None, description="photo | screenshot | document"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    conn = _conn()
    # content_type / scene live in the metrics JSON blob — pull the class out
    # with json_extract so the UI can tag and filter without a second request.
    sql = (
        "SELECT i.id, i.path, i.capture_time, i.camera_model, i.lens_model, "
        "i.iso, i.f_number, i.exposure_time, i.width, i.height, i.content_hash, i.library_id, "
        "v.verdict, v.stars, v.label, v.reasons, v.user_override, "
        "bm.burst_id, bm.is_best, "
        "json_extract(m.json, '$.content_type.class') AS content_type, "
        "json_extract(m.json, '$.scene.primary') AS scene, "
        "json_extract(m.json, '$.sharpness.score') AS sharpness, "
        "json_extract(m.json, '$.aesthetic_score') AS aesthetic_score, "
        "json_extract(m.json, '$.color') AS color_json, "
        "json_extract(m.json, '$.ocr') AS ocr_json, "
        "json_extract(m.json, '$.animals') AS animals_json "
        "FROM images i "
        "LEFT JOIN verdicts v ON v.image_id = i.id "
        "LEFT JOIN metrics m ON m.image_id = i.id "
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
    if content_type:
        where.append("json_extract(m.json, '$.content_type.class') = ?")
        params.append(content_type)
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
                "content_type": r["content_type"],
                "scene": r["scene"],
                "sharpness": float(r["sharpness"]) if r["sharpness"] is not None else 0.0,
                "aesthetic_score": float(r["aesthetic_score"]) if r["aesthetic_score"] is not None else None,
                "color": json.loads(r["color_json"]) if r["color_json"] else None,
                "ocr": json.loads(r["ocr_json"]) if r["ocr_json"] else [],
                "animals": json.loads(r["animals_json"]) if r["animals_json"] else [],
                "exposure_time": _fmt_exposure(r["exposure_time"]),
                "lens": r["lens_model"],
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


def _resolve_image_path(conn: sqlite3.Connection, image_id: int) -> tuple[Path, str | None] | None:
    """Return (path, content_hash) for an image, or None if the file is gone.

    Deliberately cheap: a single stat. Earlier this walked the whole library
    and content-hashed every file to "heal" a drifted path — on a request
    thread, for every thumbnail of a moved file, that pegged the CPU. Path
    healing now lives in the background reconcile (`_reconcile_library`, run by
    POST /libraries/{id}/sync), so a missing file just returns 410 here and the
    user re-syncs to rebind.
    """
    row = conn.execute(
        "SELECT path, content_hash FROM images WHERE id = ?", (image_id,)
    ).fetchone()
    if not row:
        return None
    path = Path(row["path"])
    if path.exists():
        return path, row["content_hash"]
    return None


@app.get("/api/images/{image_id}/thumb")
def get_thumb(image_id: int, size: int = Query(512, ge=64, le=2048)) -> Response:
    conn = _conn()
    resolved = _resolve_image_path(conn, image_id)
    if resolved is None:
        # Distinguish "no such image" from "file genuinely gone".
        exists = conn.execute("SELECT 1 FROM images WHERE id = ?", (image_id,)).fetchone()
        raise HTTPException(410 if exists else 404, "source file missing")
    path, content_hash = resolved
    out = thumb.get_or_build(path, content_hash, long_edge=size)
    return FileResponse(out, media_type="image/jpeg")


@app.get("/api/images/{image_id}/preview")
def get_preview(image_id: int) -> Response:
    conn = _conn()
    resolved = _resolve_image_path(conn, image_id)
    if resolved is None:
        exists = conn.execute("SELECT 1 FROM images WHERE id = ?", (image_id,)).fetchone()
        raise HTTPException(410 if exists else 404, "source file missing")
    path, _ = resolved
    data = thumb.render_to_bytes(path, long_edge=1600)
    return Response(content=data, media_type="image/jpeg")


class VerdictUpdate(BaseModel):
    verdict: str | None = None
    stars: int | None = None
    label: str | None = None


@app.post("/api/images/{image_id}/verdict", dependencies=[Depends(require_local)])
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


@app.post("/api/ingest", dependencies=[Depends(require_local)])
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
    model_list = [m.strip() for m in models.split(",") if m.strip() in _AVAILABLE_MODEL_NAMES]

    _claim_db_task(INGEST_STATE)
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
                from datetime import datetime as _dt, timezone as _tz
                bg_conn = _conn()
                now = _dt.now(_tz.utc).isoformat()
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


@app.post("/api/group", dependencies=[Depends(require_local)])
def regroup(hamming: int = 10, seconds: int = 3, library_id: int | None = Query(None)) -> dict[str, Any]:
    conn = _conn()
    bursts = group.group_bursts(
        conn,
        group.BurstConfig(hamming_threshold=hamming, time_window_seconds=seconds),
        library_id=library_id,
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


@app.get("/api/bursts/{burst_id}")
def get_burst(burst_id: int) -> dict[str, Any]:
    """All images in a burst, in the same shape as /api/images items."""
    return list_images(burst=burst_id, limit=200)


class BurstBest(BaseModel):
    image_id: int


@app.patch("/api/bursts/{burst_id}/best", dependencies=[Depends(require_local)])
def set_burst_best(burst_id: int, payload: BurstBest) -> dict[str, Any]:
    """Persist the user's best-of-burst pick. 404 if the image isn't in the burst."""
    conn = _conn()
    if not db.set_burst_best(conn, burst_id, payload.image_id):
        raise HTTPException(404, f"image {payload.image_id} not in burst {burst_id}")
    return {"ok": True, "burst_id": burst_id, "best_image_id": payload.image_id}


@app.post("/api/faces/run", dependencies=[Depends(require_local)])
def faces_run(
    background: BackgroundTasks,
    incremental: bool = Query(False),
    threshold: float | None = Query(None, ge=0.0, le=1.0),
) -> dict[str, Any]:
    """Detect faces (InsightFace) and cluster them (greedy/HNSW), in background.
    Status reported via /api/stats.faces. Threshold defaults to FaceClusterConfig."""
    from . import face_cluster

    _claim_db_task(FACES_STATE)

    def _run() -> None:
        FACES_STATE.update(
            running=True, stage="detect",
            done=0, total=None, detected=0, clusters=0, error=None,
        )

        def _on_progress(done: int, total: int) -> None:
            FACES_STATE["done"] = done
            FACES_STATE["total"] = total

        try:
            conn = _conn()
            cfg = (
                face_cluster.FaceClusterConfig()
                if threshold is None
                else face_cluster.FaceClusterConfig(similarity_threshold=threshold)
            )
            FACES_STATE["detected"] = face_cluster.detect_and_store(conn, cfg, progress_cb=_on_progress)
            FACES_STATE["stage"] = "cluster"
            # Clustering itself is fast and atomic — flip to indeterminate.
            FACES_STATE["done"] = 0
            FACES_STATE["total"] = None
            if incremental:
                res = face_cluster.cluster_incremental(conn, cfg)
                FACES_STATE["clusters"] = int(res.get("assigned_existing", 0)) + int(res.get("new_clusters", 0))
            else:
                FACES_STATE["clusters"] = int(face_cluster.cluster(conn, cfg))
            FACES_STATE["stage"] = "done"
        except Exception as e:
            FACES_STATE["error"] = str(e)
        finally:
            FACES_STATE["running"] = False

    background.add_task(_run)
    return {"started": True, "incremental": incremental}


@app.get("/api/faces/clusters")
def faces_clusters(
    library_id: int | None = Query(None),
    thumbs_per: int = Query(12, ge=1, le=48),
    min_size: int = Query(5, ge=1, le=1000, description="Hide clusters with fewer than N member images"),
) -> dict[str, Any]:
    """Cluster reps + member-image samples. Powers the Faces tab."""
    conn = _conn()
    # Best (highest-quality) face per cluster — image_id + bbox for crop hints.
    from . import face_cluster
    best = face_cluster.best_faces_per_cluster(conn)
    if not best:
        return {"items": []}
    labels = face_cluster.get_labels(conn)
    # Per-cluster counts and sampled member images, scoped by library_id if given.
    items: list[dict[str, Any]] = []
    for cid, rep in sorted(best.items()):
        params: list[Any] = [cid]
        scope_sql = ""
        if library_id is not None:
            scope_sql = " AND i.library_id = ?"
            params.append(library_id)
        cnt = conn.execute(
            f"SELECT COUNT(DISTINCT f.image_id) AS c FROM faces f "
            f"JOIN images i ON i.id = f.image_id WHERE f.cluster_id = ?{scope_sql}",
            params,
        ).fetchone()["c"]
        if cnt < min_size:
            continue
        # One representative face per image (SQLite returns the f.id/image_id from
        # the MAX(quality) row), so a "remove this face" acts on the right face.
        rows = conn.execute(
            f"SELECT f.id AS face_id, f.image_id, MAX(f.quality) AS q FROM faces f "
            f"JOIN images i ON i.id = f.image_id WHERE f.cluster_id = ?{scope_sql} "
            f"GROUP BY f.image_id ORDER BY q DESC NULLS LAST LIMIT ?",
            [*params, thumbs_per],
        ).fetchall()
        items.append({
            "id": int(cid),
            "label": labels.get(int(cid)) or f"Cluster {cid}",
            "named": int(cid) in labels,
            "count": int(cnt),
            "rep_image_id": int(rep["image_id"]),
            "rep_thumb": f"/api/images/{int(rep['image_id'])}/thumb?size=256",
            "thumbs": [
                {"id": int(r["image_id"]),
                 "image_id": int(r["image_id"]),
                 "face_id": int(r["face_id"]),
                 "url": f"/api/images/{int(r['image_id'])}/thumb?size=256"}
                for r in rows
            ],
        })
    return {"items": items}


class ClusterLabel(BaseModel):
    label: str


class ClusterMerge(BaseModel):
    into: int
    from_: int = Field(alias="from")

    model_config = {"populate_by_name": True}


class FaceReassign(BaseModel):
    cluster_id: int | None = None


@app.post("/api/faces/clusters/{cluster_id}/label", dependencies=[Depends(require_local)])
def label_cluster(cluster_id: int, payload: ClusterLabel) -> dict[str, Any]:
    from . import face_cluster
    conn = _conn()
    face_cluster.set_label(conn, cluster_id, payload.label)
    return {"ok": True, "cluster_id": cluster_id, "label": payload.label.strip()}


@app.post("/api/faces/clusters/merge", dependencies=[Depends(require_local)])
def merge_clusters_endpoint(payload: ClusterMerge) -> dict[str, Any]:
    from . import face_cluster
    conn = _conn()
    moved = face_cluster.merge_clusters(conn, payload.into, payload.from_)
    return {"ok": True, "into": payload.into, "from": payload.from_, "moved": moved}


@app.post("/api/faces/{face_id}/cluster", dependencies=[Depends(require_local)])
def reassign_face(face_id: int, payload: FaceReassign) -> dict[str, Any]:
    from . import face_cluster
    conn = _conn()
    if not face_cluster.set_face_cluster(conn, face_id, payload.cluster_id):
        raise HTTPException(404, f"face {face_id} not found")
    return {"ok": True, "face_id": face_id, "cluster_id": payload.cluster_id}


@app.get("/api/faces/clusters/preview")
def faces_preview(threshold: float = Query(..., ge=0.0, le=1.0)) -> dict[str, Any]:
    """Cluster count at a candidate threshold without persisting."""
    from . import face_cluster
    return face_cluster.preview_cluster_count(_conn(), threshold)


@app.get("/api/faces/clusters/{cluster_id}/best")
def faces_cluster_best(cluster_id: int) -> dict[str, Any]:
    """Highest-quality face in a single cluster — powers "best photo of X"."""
    from . import face_cluster
    conn = _conn()
    rep = face_cluster.best_photo_for_cluster(conn, cluster_id)
    if rep is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    return {
        "cluster_id": int(cluster_id),
        "image_id": rep["image_id"],
        "quality": rep["quality"],
        "bbox": rep["bbox"],
        "thumb": f"/api/images/{rep['image_id']}/thumb?size=512",
    }


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


@app.post("/api/organize", dependencies=[Depends(require_local)])
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
    written = organize.apply_plan(plan, mode=req.mode, dry_run=not req.apply, conn=conn)
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


@app.post("/api/reclassify", dependencies=[Depends(require_local)])
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


@app.post("/api/images/{image_id}/xmp", dependencies=[Depends(require_local)])
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
