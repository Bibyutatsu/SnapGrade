"""Orchestrator: walk a folder, analyze each image, persist to SQLite.

The current implementation runs single-threaded for clarity and to keep
MediaPipe happy (its TFLite delegates dislike being shared across processes).
The next step is splitting OpenCV-heavy steps into a process pool while
keeping MediaPipe on the main thread.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import db, decide, decode, exif
from .metrics import aesthetic, composition, exposure, eyes, noise, phash, sharpness, subject

log = logging.getLogger(__name__)


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
        # Hash only first chunk for speed — collision probability is fine
        # for our use (matching DB rows after rename/move).
        h.update(f.read(chunk))
    return h.hexdigest()


def _dc_to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return asdict(obj)
    return obj


def analyze_one(path: Path, max_edge: int = 2000) -> AnalysisResult:
    img = decode.decode(path, max_edge=max_edge)
    rgb = img.rgb

    subjects = subject.detect_subjects(rgb)
    bbox = subject.primary_bbox(subjects)

    sharp_global = sharpness.measure(rgb)
    sharp_subject = sharpness.measure(rgb, bbox) if bbox else None
    expo = exposure.measure(rgb)
    eye_report = eyes.measure(rgb)
    sigma = noise.estimate_sigma(rgb)
    comp = composition.measure(rgb, bbox)
    hashes = phash.compute(rgb)
    aesthetic_score = aesthetic.score(rgb)

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
    verdict = decide.decide(metrics)
    return AnalysisResult(path=path, metrics=metrics, verdict=verdict)


def analyze_folder(
    root: Path,
    db_path: Path | None = None,
    force: bool = False,
    max_edge: int = 2000,
) -> Iterator[AnalysisResult]:
    conn = db.connect(db_path) if db_path else db.connect()
    for p in walk_images(root):
        try:
            st = p.stat()
            if not force and not db.needs_analysis(conn, str(p), st.st_mtime):
                continue
            result = analyze_one(p, max_edge=max_edge)
            ex = exif.read_exif(p)
            fields = {
                "path": str(p),
                "size_bytes": st.st_size,
                "mtime": st.st_mtime,
                "content_hash": _content_hash(p),
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
            yield result
        except Exception as e:
            log.exception("Failed to analyze %s: %s", p, e)
            continue


def analyze_folder_collect(root: Path, **kwargs: Any) -> list[AnalysisResult]:
    return list(analyze_folder(root, **kwargs))
