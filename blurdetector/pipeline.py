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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import db, decide, decode, exif
from .metrics import aesthetic, composition, exposure, eyes, noise, phash, sharpness, subject

log = logging.getLogger(__name__)

_ML_LOCK = threading.Lock()


@dataclass(frozen=True)
class AnalysisResult:
    path: Path
    metrics: dict[str, Any]
    verdict: decide.Verdict


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


def analyze_one(path: Path, max_edge: int = 2000, models: list[str] | None = None) -> AnalysisResult:
    img = decode.decode(path, max_edge=max_edge)
    rgb = img.rgb
    enabled = set(models or [])

    # ML phase: YuNet and MediaPipe are not thread-safe — serialize.
    with _ML_LOCK:
        subjects = subject.detect_subjects(rgb)
        eye_report = eyes.measure(rgb, faces=subjects)
        aesthetic_score = aesthetic.score(rgb)
        extra: dict[str, Any] = {}
        if "scene" in enabled:
            try:
                from .metrics import scene as _scene
                extra["scene"] = _scene.analyze(rgb)
            except Exception as e:  # pragma: no cover - opt-in
                extra["scene_error"] = str(e)
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
        if "screendoc" in enabled:
            try:
                from .metrics import screendoc as _sd
                extra["screendoc"] = _sd.analyze(rgb)
            except Exception as e:  # pragma: no cover
                extra["screendoc_error"] = str(e)

    bbox = subject.primary_bbox(subjects)
    sharp_global = sharpness.measure(rgb)
    sharp_subject = sharpness.measure(rgb, bbox) if bbox else None
    expo = exposure.measure(rgb)
    sigma = noise.estimate_sigma(rgb)
    comp = composition.measure(rgb, bbox)
    hashes = phash.compute(rgb)

    metrics: dict[str, Any] = {
        "sharpness": _dc_to_dict(sharp_global),
        "subject_sharpness": _dc_to_dict(sharp_subject) if sharp_subject else None,
        "subjects": [_dc_to_dict(s) for s in subjects],
        "exposure": _dc_to_dict(expo),
        "eyes": _dc_to_dict(eye_report),
        "noise_sigma": sigma,
        "aesthetic_score": aesthetic_score,
        "composition": _dc_to_dict(comp),
        "hashes": _dc_to_dict(hashes),
        "source_size": [img.source_w, img.source_h],
        "kind": img.kind,
    }
    metrics.update(extra)
    return AnalysisResult(path=path, metrics=metrics, verdict=decide.decide(metrics))


def _persist(conn, path: Path, result: AnalysisResult, st_size: int, st_mtime: float, library_id: int | None = None) -> None:
    ex = exif.read_exif(path)
    fields = {
        "path": str(path),
        **({"library_id": library_id} if library_id is not None else {}),
        "size_bytes": st_size,
        "mtime": st_mtime,
        "content_hash": _content_hash(path),
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
    with db.transaction(conn):
        image_id = db.upsert_image(conn, fields)
        db.save_metrics(conn, image_id, result.metrics)
        db.save_verdict(
            conn,
            image_id,
            result.verdict.verdict,
            result.verdict.stars,
            result.verdict.label,
            result.verdict.reasons,
        )


def _default_workers() -> int:
    # Sweet spot on the M1 Air: enough threads to keep decode busy while the
    # ML lock is held, without thrashing the 8 GB unified RAM with N decoded
    # 2000-px arrays in flight.
    return min(4, max(1, (os.cpu_count() or 4) - 2))


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

    if n_workers <= 1:
        for p, st in pending:
            try:
                r = analyze_one(p, max_edge=max_edge, models=models)
                _persist(conn, p, r, st.st_size, st.st_mtime, library_id=library_id)
                yield r
            except Exception as e:
                log.exception("Failed to analyze %s: %s", p, e)
        return

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(analyze_one, p, max_edge, models): (p, st) for p, st in pending}
        for fut in as_completed(futures):
            p, st = futures[fut]
            try:
                r = fut.result()
                _persist(conn, p, r, st.st_size, st.st_mtime, library_id=library_id)
                yield r
            except Exception as e:
                log.exception("Failed to analyze %s: %s", p, e)


def analyze_folder_collect(root: Path, **kwargs: Any) -> list[AnalysisResult]:
    return list(analyze_folder(root, **kwargs))
