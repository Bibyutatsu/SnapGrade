"""Orchestrator: walk a folder, analyze each image, persist to SQLite.

Per-image phases:

  CPU-parallel (release the GIL — runs free across threads):
    decode, sharpness, exposure, noise, composition, phash, exif

  ML-serialized (YuNet + MediaPipe FaceLandmarker; not thread-safe):
    face detection, eye landmarks

A single threading.Lock serializes the ML phase. With a moderate number of
workers (4–8), the parallel phase fills the time the ML phase would otherwise
sit idle, giving ~2× wall-clock speedup on the M1 Air.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import db, decide, decode, exif
from .metrics import aesthetic, color, composition, exposure, face_expression, noise, phash, sharpness, subject

log = logging.getLogger(__name__)

_ML_LOCK = threading.Lock()


@dataclass(frozen=True)
class AnalysisResult:
    path: Path
    metrics: dict[str, Any]
    verdict: decide.Verdict
    # Filled in the worker thread so the consumer's persist phase is pure DB
    # work — no extra file I/O while a transaction is open. Both default to
    # None for callers (CLI `show`) that build a result directly.
    exif: exif.Exif | None = None
    content_hash: str | None = None
    # MobileCLIP image embedding when SNAPGRADE_ENABLE_SEMANTIC=1; None otherwise.
    # Stored as packed float32 bytes for direct INSERT into image_embeddings.
    embedding: bytes | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None


def walk_images(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        if p.is_file() and decode.is_supported(p):
            yield p


def _content_hash(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        h.update(f.read(chunk))
    return h.hexdigest()


def _dc_to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return asdict(obj)
    return obj


_LIVE_VIDEO_EXTS = (".mov", ".MOV", ".mp4", ".MP4")


def _live_photo_video(path: Path) -> Path | None:
    """A sibling video with the same stem marks an iOS/Android Live Photo."""
    for ext in _LIVE_VIDEO_EXTS:
        cand = path.with_suffix(ext)
        if cand != path and cand.exists():
            return cand
    return None


def analyze_one(path: Path, max_edge: int = 2000, models: list[str] | None = None) -> AnalysisResult:
    t0 = time.perf_counter()
    img = decode.decode(path, max_edge=max_edge)
    t_decode = time.perf_counter() - t0
    # Read EXIF + content_hash here (in the worker thread) so the consumer's
    # persist phase doesn't re-open the file under a held DB transaction.
    ex = exif.read_exif(path)
    ch = _content_hash(path)
    return _analyze_from_decoded(
        path, img, models=models, t_decode=t_decode, exif_record=ex, content_hash=ch,
    )


def _analyze_from_decoded(
    path: Path,
    img: Any,
    models: list[str] | None = None,
    t_decode: float = 0.0,
    exif_record: exif.Exif | None = None,
    content_hash: str | None = None,
) -> AnalysisResult:
    """The post-decode half of analyze_one. Used directly by the staged
    pipeline (decoder pool → consumer) so the consumer doesn't repeat decode.
    """
    rgb = img.rgb
    enabled = set(models or [])
    t_ml_start = time.perf_counter()

    # ML phase. Only MediaPipe FaceLandmarker truly needs the global lock — its
    # Tasks runtime crashes when reentered from multiple threads. Everything
    # else runs concurrently:
    #   - YuNet: per-thread instances (see subject._YUNET_LOCAL).
    #   - CoreML predict: Apple's MLModel.predict is thread-safe; the ANE/GPU
    #     serializes internally so we don't gain ANE parallelism, but other
    #     workers stay free to decode/CV while one runs inference.
    #   - Apple Vision: VNImageRequestHandler is per-call, also thread-safe.
    subjects = subject.detect_subjects(rgb)
    extra: dict[str, Any] = {}
    # Run object/saliency models BEFORE blink so primaries can be disambiguated
    # from a crowd by foreground signals.
    if "subject_seg" in enabled:
        try:
            from .metrics import subject_seg as _ss
            extra["subject_seg"] = _ss.analyze(rgb)
        except Exception as e:  # pragma: no cover
            extra["subject_seg_error"] = str(e)
    if "objects" in enabled:
        try:
            from .metrics import objects as _obj
            extra["objects"] = _obj.analyze(rgb)
        except Exception as e:  # pragma: no cover
            extra["objects_error"] = str(e)
    if "depth" in enabled:
        try:
            from .metrics import depth as _depth
            extra["depth"] = _depth.analyze(rgb)
        except Exception as e:  # pragma: no cover
            extra["depth_error"] = str(e)

    salient_bbox = None
    if isinstance(extra.get("subject_seg"), dict):
        salient_bbox = extra["subject_seg"].get("bbox")
    person_bboxes: list[list[int]] = []
    if isinstance(extra.get("objects"), dict):
        for d in extra["objects"].get("detections", []) or []:
            if d.get("class") == "person" and d.get("bbox"):
                person_bboxes.append(d["bbox"])
    primaries = subject.primary_subjects(
        subjects, rgb.shape,
        salient_bbox=salient_bbox,
        person_bboxes=person_bboxes or None,
    )

    # MediaPipe blendshape pass — the one piece that must be serialized.
    with _ML_LOCK:
        eye_report = face_expression.measure(rgb, faces=primaries)

    aesthetic_score, aesthetic_source = aesthetic.score(rgb)
    if "scene" in enabled:
        try:
            from .metrics import scene as _scene
            extra["scene"] = _scene.analyze(rgb)
        except Exception as e:  # pragma: no cover - opt-in
            extra["scene_error"] = str(e)
    # Content type (screenshot / document / photo) + OCR + animals via Apple
    # Vision. OPT-IN: pass any of "content_type" / "ocr" / "vision" in the
    # models list to enable. Vision OCR is the dominant per-image ML cost on
    # photo libraries (~0.3-0.5s/image) and is wasted on the 99%+ of camera
    # photos that are clearly not screenshots — so it's off by default.
    # Back-compat: "screendoc" is an alias for the old screendoc model.
    # "no_content_type" remains an explicit kill-switch.
    from .metrics import vision as _vis
    want_content = (
        "no_content_type" not in enabled
        and _vis.is_available()
        and bool(enabled & {"content_type", "ocr", "vision", "screendoc"})
    )
    if want_content:
        try:
            # Camera-EXIF presence is the strongest content-type signal:
            # screenshots/docs never carry a camera model. When present, we
            # skip the OCR + document-segmentation hop entirely (cheap
            # photo-class fast path) — unless the caller explicitly asked
            # for OCR text.
            _ex_for_cam = exif_record if exif_record is not None else exif.read_exif(path)
            has_camera = bool(_ex_for_cam.camera_model)
            want_ocr_always = bool(enabled & {"ocr", "vision"})
            if has_camera and not want_ocr_always:
                extra["ocr"] = []
                extra["content_type"] = {
                    "class": "photo", "conf": 0.95, "source": "exif_fastpath",
                    "has_camera": True,
                }
            else:
                ocr_regions = _vis.recognize_text(rgb)
                extra["ocr"] = ocr_regions
                from .metrics import content_type as _ct
                extra["content_type"] = _ct.analyze(
                    rgb, ocr_regions=ocr_regions, has_camera=has_camera,
                )
            animals = _vis.recognize_animals(rgb)
            if animals:
                extra["animals"] = animals
        except Exception as e:  # pragma: no cover
            extra["content_type_error"] = str(e)
    t_ml = time.perf_counter() - t_ml_start

    t_cv_start = time.perf_counter()
    # Prefer the largest primary subject's bbox for subject-aware sharpness.
    bbox = primaries[0].bbox if primaries else subject.primary_bbox(subjects)
    sharp_global = sharpness.measure(rgb)
    sharp_subject = sharpness.measure(rgb, bbox) if bbox else None
    expo = exposure.measure(rgb)
    sigma = noise.estimate_sigma(rgb)
    comp = composition.measure(rgb, bbox)
    color_info = color.measure(rgb)
    hashes = phash.compute(rgb)
    primary_set = {id(s) for s in primaries}
    seen_ids = set()
    subjects_dump = []
    for s in subjects:
        d = _dc_to_dict(s)
        d["is_primary"] = id(s) in primary_set
        subjects_dump.append(d)
        seen_ids.add(id(s))
    # Include any synthesised primary (e.g. person bbox from YOLO when no
    # face was detected) so the UI renders something to focus on.
    for s in primaries:
        if id(s) in seen_ids:
            continue
        d = _dc_to_dict(s)
        d["is_primary"] = True
        subjects_dump.append(d)
    metrics: dict[str, Any] = {
        "sharpness": _dc_to_dict(sharp_global),
        "subject_sharpness": _dc_to_dict(sharp_subject) if sharp_subject else None,
        "subjects": subjects_dump,
        "exposure": _dc_to_dict(expo),
        "eyes": _dc_to_dict(eye_report),
        "noise_sigma": sigma,
        "aesthetic_score": aesthetic_score,
        "aesthetic_source": aesthetic_source,
        "composition": _dc_to_dict(comp),
        "color": _dc_to_dict(color_info),
        "hashes": _dc_to_dict(hashes),
        "source_size": [img.source_w, img.source_h],
        "decoded_size": [int(rgb.shape[1]), int(rgb.shape[0])],
        "kind": img.kind,
    }
    live_video = _live_photo_video(path)
    if live_video is not None:
        metrics["live_photo"] = {"video": str(live_video)}
    metrics.update(extra)
    t_cv = time.perf_counter() - t_cv_start

    emb_bytes: bytes | None = None
    emb_model: str | None = None
    emb_dim: int | None = None
    if os.environ.get("SNAPGRADE_ENABLE_SEMANTIC") or "semantic" in enabled:
        try:
            from .metrics import embed as _embed
            vec = _embed.compute(rgb)
            if vec is not None:
                emb_bytes = vec.tobytes()
                emb_model = _embed.MODEL_NAME
                emb_dim = int(vec.size)
        except Exception as e:  # pragma: no cover - opt-in
            metrics["embedding_error"] = str(e)

    metrics["t_decode_s"] = round(t_decode, 4)
    metrics["t_ml_s"] = round(t_ml, 4)
    metrics["t_cv_s"] = round(t_cv, 4)
    return AnalysisResult(
        path=path,
        metrics=metrics,
        verdict=decide.decide(metrics),
        exif=exif_record,
        content_hash=content_hash,
        embedding=emb_bytes,
        embedding_model=emb_model,
        embedding_dim=emb_dim,
    )


def _persist_row(conn, path: Path, result: AnalysisResult, st_size: int, st_mtime: float, library_id: int | None = None) -> None:
    """Persist a single analysis result. Caller MUST hold an open transaction —
    batched writes amortize per-row commit cost on big-library runs.

    Falls back to reading EXIF / content_hash here only if the worker thread
    didn't pre-populate them (e.g. an older AnalysisResult shape).
    """
    ex = result.exif if result.exif is not None else exif.read_exif(path)
    ch = result.content_hash if result.content_hash is not None else _content_hash(path)
    fields = {
        "path": str(path),
        **({"library_id": library_id} if library_id is not None else {}),
        "size_bytes": st_size,
        "mtime": st_mtime,
        "content_hash": ch,
        "kind": result.metrics["kind"],
        "width": result.metrics["source_size"][0],
        "height": result.metrics["source_size"][1],
        "capture_time": ex.capture_time.isoformat() if ex.capture_time else None,
        "camera_make": ex.camera_make,
        "camera_model": ex.camera_model,
        "lens_model": ex.lens_model,
        "iso": ex.iso,
        "f_number": ex.f_number,
        "exposure_time": ex.exposure_time,
        "focal_length_mm": ex.focal_length_mm,
        "orientation": ex.orientation,
        "gps_lat": ex.gps_lat,
        "gps_lon": ex.gps_lon,
        "phash": result.metrics["hashes"]["phash"],
        "dhash": result.metrics["hashes"]["dhash"],
        "analyzed_at": datetime.utcnow().isoformat(),
    }
    image_id = db.upsert_image(conn, fields)
    db.save_metrics(conn, image_id, result.metrics)
    if result.embedding is not None and result.embedding_model and result.embedding_dim:
        db.save_embedding(
            conn, image_id, result.embedding_model, result.embedding, result.embedding_dim,
        )
    db.save_verdict(
        conn,
        image_id,
        result.verdict.verdict,
        result.verdict.stars,
        result.verdict.label,
        result.verdict.reasons,
    )


def _persist(conn, path: Path, result: AnalysisResult, st_size: int, st_mtime: float, library_id: int | None = None) -> None:
    """Single-row persist with its own transaction (back-compat path)."""
    with db.transaction(conn):
        _persist_row(conn, path, result, st_size, st_mtime, library_id=library_id)


PERSIST_BATCH = 50  # rows flushed per outer transaction in analyze_folder


def _default_workers() -> int:
    # SNAPGRADE_WORKERS overrides; otherwise 4 is the sweet spot on the M1 Air —
    # enough threads to keep decode + post-CV busy while the ML lock is held by
    # one worker, without thrashing 8 GB RAM with N decoded 2000-px arrays.
    env = os.environ.get("SNAPGRADE_WORKERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return min(4, max(1, (os.cpu_count() or 4) - 2))


# Cap concurrent in-flight images (per worker). With a 2000-px decode at ~25 MB
# RGB + intermediate buffers, 2× workers in flight is the ceiling before peak
# RSS climbs past ~2.5 GB on M1 Air. Process pool is more sensitive than
# threads since each worker has its own model RSS.
_INFLIGHT_PER_WORKER = 2




def analyze_folder(
    root: Path,
    db_path: Path | None = None,
    force: bool = False,
    max_edge: int = 2000,
    workers: int | None = None,
    models: list[str] | None = None,
    library_id: int | None = None,
) -> Iterator[AnalysisResult]:
    conn = db.connect(db_path) if db_path else db.connect()
    if library_id is None:
        library_id = db.ensure_library(conn, str(root))

    pending: list[tuple[Path, os.stat_result]] = []
    for p in walk_images(root):
        st = p.stat()
        if not force and not db.needs_analysis(conn, str(p), st.st_mtime):
            continue
        pending.append((p, st))
    if not pending:
        return

    n_workers = workers if workers is not None else _default_workers()

    # Batched writer: keep a running transaction open across PERSIST_BATCH rows,
    # then commit. Cuts BEGIN/COMMIT overhead from ~1/image to ~1/50 images.
    buf: list[tuple[Path, AnalysisResult, int, float]] = []

    def _flush() -> None:
        if not buf:
            return
        with db.transaction(conn):
            for bp, br, bsz, bmt in buf:
                _persist_row(conn, bp, br, bsz, bmt, library_id=library_id)
        buf.clear()

    if n_workers <= 1:
        for p, st in pending:
            try:
                r = analyze_one(p, max_edge=max_edge, models=models)
                buf.append((p, r, st.st_size, st.st_mtime))
                if len(buf) >= PERSIST_BATCH:
                    _flush()
                yield r
            except Exception as e:
                log.exception("Failed to analyze %s: %s", p, e)
        _flush()
        return

    # Per-image worker: decode → ML (serialised on _ML_LOCK) → post-CV. The
    # lock means only one thread is in the ML phase at a time, but the others
    # stay busy decoding the next image and running post-CV on the previous
    # one. Empirically faster than a single-consumer staged pipeline because
    # the post-CV (sharpness/exposure/noise/composition/phash) actually
    # parallelises well across threads.
    #
    # SNAPGRADE_USE_PROCESSES=1 swaps the thread pool for a process pool —
    # useful on Intel Macs (no ANE) where GIL contention on heavier post-CV
    # work can dominate. Default (threads) is the right call on Apple Silicon
    # because native libs already release the GIL during decode/inference.
    use_processes = bool(os.environ.get("SNAPGRADE_USE_PROCESSES"))
    from concurrent.futures import ProcessPoolExecutor, as_completed
    PoolCls = ProcessPoolExecutor if use_processes else ThreadPoolExecutor
    # Bound in-flight work to cap peak RSS. Submitting all `pending` up front
    # would queue every decoded array in memory; instead we keep ~2× workers
    # in flight and refill as futures complete.
    inflight_cap = max(n_workers * _INFLIGHT_PER_WORKER, n_workers + 1)
    with PoolCls(max_workers=n_workers) as pool:
        it = iter(pending)
        futures: dict = {}

        def _submit_next() -> bool:
            try:
                p, st = next(it)
            except StopIteration:
                return False
            futures[pool.submit(analyze_one, p, max_edge, models)] = (p, st)
            return True

        for _ in range(inflight_cap):
            if not _submit_next():
                break

        while futures:
            for fut in as_completed(list(futures)):
                p, st = futures.pop(fut)
                try:
                    r = fut.result()
                    buf.append((p, r, st.st_size, st.st_mtime))
                    if len(buf) >= PERSIST_BATCH:
                        _flush()
                    yield r
                except Exception as e:
                    log.exception("Failed to analyze %s: %s", p, e)
                _submit_next()
                break
    _flush()


def analyze_folder_collect(root: Path, **kwargs: Any) -> list[AnalysisResult]:
    return list(analyze_folder(root, **kwargs))
