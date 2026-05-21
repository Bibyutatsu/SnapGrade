"""End-to-end benchmark for `analyze_folder` on the Images/ corpus.

This is an opt-in profiling harness — not a pytest. Run modes:

    # Capture a baseline (writes label="baseline" to bench_results.md).
    uv run python -m tests.bench_pipeline --label baseline

    # Compare against the last baseline run (writes a row + a delta column).
    uv run python -m tests.bench_pipeline --label "B.1 compute_units"

    # Custom corpus / SQLite path:
    uv run python -m tests.bench_pipeline --label foo --root /tmp/photos

Records wall time, peak RSS, images/sec, and a coarse stage breakdown
(decode+EXIF, inference, persist) to `bench_results.md` so each performance
PR can quote its own number.

Each run uses a fresh temp DB so warm-mtime skipping doesn't poison the
measurement; pass `--reuse-db` to measure the steady-state warm path instead.
"""

from __future__ import annotations

import argparse
import os
import resource
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_ROOT = Path(os.environ.get("SNAPGRADE_IMAGES_ROOT", "/Users/oindrila/Projects/BlurDetector/Images"))
RESULTS_FILE = Path(__file__).resolve().parent.parent / "bench_results.md"


def _peak_rss_mb() -> float:
    # ru_maxrss is bytes on macOS, KB on Linux.
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return rss / (1024 * 1024)
    return rss / 1024


def _stage_times_from_metrics(metrics: dict) -> tuple[float, float]:
    """Coarse split: assume decode/EXIF/cheap-CV stages report `t_decode_s`
    when populated by pipeline instrumentation; otherwise return 0s. Inference
    time is everything else minus persist (persist measured separately at the
    caller level)."""
    decode = float(metrics.get("t_decode_s") or 0.0)
    infer = float(metrics.get("t_infer_s") or 0.0)
    return decode, infer


def run(label: str, root: Path, reuse_db: bool, max_edge: int) -> None:
    from snapgrade import db, pipeline

    if not root.is_dir():
        print(f"ERROR: corpus root not found: {root}", file=sys.stderr)
        sys.exit(2)

    if reuse_db:
        db_path = Path.home() / ".snapgrade" / "library.db"
    else:
        td = tempfile.mkdtemp(prefix="snapgrade-bench-")
        db_path = Path(td) / "bench.db"

    files_total = sum(1 for _ in pipeline.walk_images(root))
    if files_total == 0:
        print(f"ERROR: no images found under {root}", file=sys.stderr)
        sys.exit(2)

    # Warm caches: import heavy modules once before timing.
    db.connect(db_path).close()

    t0 = time.perf_counter()
    n = 0
    decode_sum = 0.0
    infer_sum = 0.0
    for r in pipeline.analyze_folder(root, db_path=db_path, force=not reuse_db, max_edge=max_edge):
        n += 1
        d, i = _stage_times_from_metrics(r.metrics)
        decode_sum += d
        infer_sum += i
    elapsed = time.perf_counter() - t0
    rss = _peak_rss_mb()
    ips = n / elapsed if elapsed > 0 else 0.0

    row = (
        f"| {label} | {n} | {elapsed:.2f} | {ips:.2f} | "
        f"{decode_sum:.2f} | {infer_sum:.2f} | {rss:.1f} | "
        f"{root.name} | reuse_db={reuse_db} |"
    )
    print(row)

    header = (
        "| Label | N | Wall (s) | img/s | Decode-sum (s) | Infer-sum (s) | "
        "Peak RSS (MB) | Corpus | Notes |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    if not RESULTS_FILE.exists():
        RESULTS_FILE.write_text("# SnapGrade bench results\n\n" + header)
    elif "| Label |" not in RESULTS_FILE.read_text():
        RESULTS_FILE.write_text(RESULTS_FILE.read_text() + "\n" + header)
    with RESULTS_FILE.open("a") as f:
        f.write(row + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", required=True, help="Row label written to bench_results.md")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--max-edge", type=int, default=2000)
    p.add_argument(
        "--reuse-db", action="store_true",
        help="Use ~/.snapgrade/library.db (warm mtime cache) instead of a temp DB.",
    )
    args = p.parse_args()
    run(args.label, args.root, args.reuse_db, args.max_edge)


if __name__ == "__main__":
    main()
