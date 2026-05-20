"""Bucket-labelled smoke tests against the real Images/ corpus.

The Images/ directory is organised by failure mode (Blurry Images, Eyes Closed,
Screenshots, …). Each subfolder doubles as ground truth — this harness asserts
the pipeline's verdict / metrics match the bucket's intent and prints a
per-bucket pass/fail table.

Two entry points:

    # As pytest — used in CI and `uv run pytest`.
    uv run pytest tests/smoke_images.py

    # As CLI — interactive, prints a readable table.
    uv run python -m tests.smoke_images
    uv run python -m tests.smoke_images --bucket "Eyes Closed" --verbose
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

from snapgrade import decode, pipeline

IMAGES_ROOT = Path("/Users/oindrila/Projects/BlurDetector/Images")

VALID_VERDICTS = {"keeper", "review", "reject"}


@dataclass
class Check:
    """A single bucket assertion. `fn(metrics, verdict) -> (passed, note)`."""
    name: str
    fn: Callable[[dict[str, Any], Any], tuple[bool, str]]


@dataclass
class BucketResult:
    bucket: str
    n_files: int
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)  # (filename, why)
    elapsed_s: float = 0.0


# ---------- Check predicates ----------

def _verdict_is(*allowed: str) -> Callable[[dict[str, Any], Any], tuple[bool, str]]:
    def check(_m: dict[str, Any], v: Any) -> tuple[bool, str]:
        ok = v.verdict in allowed
        return ok, f"verdict={v.verdict} reasons={v.reasons}"
    return check


def _verdict_is_valid(_m: dict[str, Any], v: Any) -> tuple[bool, str]:
    ok = v.verdict in VALID_VERDICTS
    return ok, f"verdict={v.verdict}"


def _has_blur_reason(_m: dict[str, Any], v: Any) -> tuple[bool, str]:
    joined = " ".join(v.reasons).lower()
    ok = ("blur" in joined) or ("out of focus" in joined) or ("soft" in joined) or ("motion" in joined)
    return ok, f"reasons={v.reasons}"


def _any_face_closed(m: dict[str, Any], _v: Any) -> tuple[bool, str]:
    eyes = m.get("eyes", {}) or {}
    n_faces = eyes.get("faces", 0)
    if n_faces == 0:
        return False, "no faces detected"
    closed = bool(eyes.get("any_closed"))
    min_ear = eyes.get("min_ear")
    max_blink = eyes.get("max_blink")
    return closed, f"faces={n_faces} any_closed={closed} min_ear={min_ear} max_blink={max_blink}"


def _faces_at_least(n: int) -> Callable[[dict[str, Any], Any], tuple[bool, str]]:
    def check(m: dict[str, Any], _v: Any) -> tuple[bool, str]:
        subjects = m.get("subjects") or []
        n_faces = sum(1 for s in subjects if s.get("kind") == "face")
        return n_faces >= n, f"faces={n_faces}"
    return check


def _subject_less_sharp_than_frame(min_ratio: float = 0.30) -> Callable[[dict[str, Any], Any], tuple[bool, str]]:
    """Subject sharpness should be meaningfully below frame sharpness."""
    def check(m: dict[str, Any], _v: Any) -> tuple[bool, str]:
        ss = m.get("subject_sharpness")
        sg = m.get("sharpness") or {}
        if not ss or not sg:
            return False, f"missing sharpness data (subject={bool(ss)} global={bool(sg)})"
        s_subj = ss.get("score", 0.0)
        s_frame = sg.get("score", 0.0)
        if s_frame <= 0:
            return False, "frame sharpness 0"
        ratio = (s_frame - s_subj) / s_frame
        return ratio >= min_ratio, f"subject={s_subj:.3f} frame={s_frame:.3f} delta_ratio={ratio:.2f}"
    return check


def _content_type_is(*allowed: str) -> Callable[[dict[str, Any], Any], tuple[bool, str]]:
    def check(m: dict[str, Any], _v: Any) -> tuple[bool, str]:
        ct = m.get("content_type") or {}
        cls = ct.get("class")
        return cls in allowed, f"content_type={cls} conf={ct.get('conf')} source={ct.get('source')}"
    return check


def _ocr_has_text(m: dict[str, Any], _v: Any) -> tuple[bool, str]:
    regions = m.get("ocr") or []
    return len(regions) >= 1, f"ocr_regions={len(regions)}"


def _depth_flags_misfocus(m: dict[str, Any], _v: Any) -> tuple[bool, str]:
    d = m.get("depth") or {}
    if not d:
        return False, "depth model not run (download with: snapgrade setup --only depth)"
    return bool(d.get("focus_on_background")), (
        f"focus_on_background={d.get('focus_on_background')} "
        f"near={d.get('near_sharpness'):.0f} far={d.get('far_sharpness'):.0f}"
    )


# ---------- Bucket plan ----------
# Each bucket lists the checks. Pre-Phase-3, OCR / content_type / depth checks
# don't exist yet — we soft-mark those as "future" so the baseline run isn't
# polluted by failures for things we haven't built yet.

BUCKET_PLAN: dict[str, list[Check]] = {
    "Blurry Images": [
        Check("verdict==reject", _verdict_is("reject")),
        Check("blur reason present", _has_blur_reason),
    ],
    "Eyes Closed": [
        Check("at least one face flagged closed", _any_face_closed),
    ],
    "Crowd": [
        Check("face count >= 4", _faces_at_least(4)),
    ],
    "Subject out of focus": [
        # Depth-aware mis-focus: soft foreground in front of a sharp background.
        Check("depth flags background focus", _depth_flags_misfocus),
    ],
    "Screenshots": [
        Check("classified as screenshot", _content_type_is("screenshot")),
    ],
    "Scenery with text": [
        # Text in a real scene must NOT be mistaken for a screenshot.
        Check("classified as photo", _content_type_is("photo")),
        Check("OCR finds text", _ocr_has_text),
    ],
    "Uncategorized": [
        Check("no crash, valid verdict", _verdict_is_valid),
    ],
}

# Models to enable per bucket (Vision content_type/OCR don't run by default).
BUCKET_MODELS: dict[str, list[str]] = {
    "Screenshots": ["content_type"],
    "Scenery with text": ["content_type"],
    "Subject out of focus": ["depth"],
}


# ---------- Runner ----------

def _list_files(bucket_dir: Path) -> list[Path]:
    if not bucket_dir.is_dir():
        return []
    return sorted(p for p in bucket_dir.iterdir() if p.is_file() and decode.is_supported(p))


def _analyze(path: Path, models: list[str] | None = None) -> tuple[dict[str, Any] | None, Any, str | None]:
    try:
        r = pipeline.analyze_one(path, models=models)
        return r.metrics, r.verdict, None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def run_bucket(bucket: str, checks: list[Check], verbose: bool = False) -> BucketResult:
    files = _list_files(IMAGES_ROOT / bucket)
    result = BucketResult(bucket=bucket, n_files=len(files))
    if not files:
        return result

    models = BUCKET_MODELS.get(bucket)
    t0 = time.time()
    for path in files:
        metrics, verdict, err = _analyze(path, models=models)
        if err is not None:
            result.failed += 1
            result.failures.append((path.name, f"analyze failed: {err}"))
            if verbose:
                print(f"  [FAIL] {path.name} — {err}")
            continue
        all_ok = True
        notes: list[str] = []
        for check in checks:
            ok, note = check.fn(metrics, verdict)
            notes.append(f"{check.name}: {note}")
            if not ok:
                all_ok = False
        if all_ok:
            result.passed += 1
            if verbose:
                print(f"  [PASS] {path.name}")
        else:
            result.failed += 1
            result.failures.append((path.name, " | ".join(notes)))
            if verbose:
                print(f"  [FAIL] {path.name} — {notes[-1]}")
    result.elapsed_s = time.time() - t0
    return result


def run_all(buckets: list[str] | None = None, verbose: bool = False) -> list[BucketResult]:
    if buckets is None:
        buckets = list(BUCKET_PLAN.keys())
    results: list[BucketResult] = []
    for b in buckets:
        if b not in BUCKET_PLAN:
            print(f"unknown bucket: {b} (valid: {list(BUCKET_PLAN)})", file=sys.stderr)
            continue
        if verbose:
            print(f"\n=== {b} ===")
        results.append(run_bucket(b, BUCKET_PLAN[b], verbose=verbose))
    return results


def print_table(results: list[BucketResult]) -> None:
    headers = ("bucket", "N", "pass", "fail", "skip", "time")
    rows = [
        (
            r.bucket,
            str(r.n_files),
            str(r.passed),
            str(r.failed),
            str(r.skipped),
            f"{r.elapsed_s:.1f}s" if r.elapsed_s else "-",
        )
        for r in results
    ]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)] if rows else [len(h) for h in headers]
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    total_n = total_p = total_f = 0
    for row, r in zip(rows, results):
        print(fmt.format(*row))
        total_n += r.n_files
        total_p += r.passed
        total_f += r.failed
    print(fmt.format(*("-" * w for w in widths)))
    print(fmt.format("TOTAL", str(total_n), str(total_p), str(total_f), "", ""))

    for r in results:
        if r.failures and not r.n_files == 0:
            print(f"\n— failures in '{r.bucket}' (first 5) —")
            for name, why in r.failures[:5]:
                print(f"  {name}: {why}")


# ---------- pytest entry points ----------

# Buckets the current pipeline is known to miss; tightening tracked by phase.
# When a phase lands, drop the bucket from this set. (Empty: all buckets are
# expected to pass when their required models are present.)
XFAIL_BUCKETS: dict[str, str] = {}


@pytest.mark.parametrize("bucket", list(BUCKET_PLAN.keys()))
def test_bucket(bucket: str, request) -> None:
    """One pytest case per bucket; failures list the offending files in the assertion message."""
    if not IMAGES_ROOT.is_dir():
        pytest.skip(f"Images root not found at {IMAGES_ROOT}")
    files = _list_files(IMAGES_ROOT / bucket)
    if not files:
        pytest.skip(f"bucket '{bucket}' is empty")
    if bucket in XFAIL_BUCKETS:
        request.applymarker(pytest.mark.xfail(reason=XFAIL_BUCKETS[bucket], strict=False))
    result = run_bucket(bucket, BUCKET_PLAN[bucket])
    # Baseline acceptance: at least *some* images pass. Per-phase tightening
    # happens by raising this floor — see plan file.
    msg = (
        f"\n{result.bucket}: N={result.n_files} pass={result.passed} fail={result.failed}\n"
        + "\n".join(f"  {n}: {w}" for n, w in result.failures[:10])
    )
    assert result.passed > 0, msg


# ---------- CLI ----------

def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bucket", action="append", help="Limit to one bucket (repeatable).")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if not IMAGES_ROOT.is_dir():
        print(f"Images root not found: {IMAGES_ROOT}", file=sys.stderr)
        return 2

    results = run_all(buckets=args.bucket, verbose=args.verbose)
    print()
    print_table(results)
    return 0 if all(r.failed == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
