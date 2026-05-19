# BlurDetector — Agent Index

A privacy-respecting, fully-local utility that culls and organizes photo libraries on an 8 GB MacBook Air. Built from classical CV + a few tiny purpose-built models (no large transformers / VLMs). The full design rationale lives in `/Users/oindrila/.claude/plans/i-want-you-to-polymorphic-seal.md` — read it before redesigning any layer.

## Mental model

Three decoupled layers; any one can be swapped without disturbing the others:

1. **Analyzer** — pure `image → metrics` functions. Stateless, cacheable.
2. **Decision engine** — `(metrics, thresholds) → verdict + stars + reasons`.
3. **Organizer / UI** — reads the SQLite cache, drives the UI, writes XMP sidecars, builds the user-defined hierarchical tree.

Single source of truth: `~/.blurdetector/library.db` (SQLite, WAL). Files on disk are never authoritative — re-runs are idempotent. Thumbnails cached at `~/.blurdetector/thumbs/`.

## Where things live

| Concern | File | Notes |
|---|---|---|
| Image decoding (RAW / HEIC / JPEG, bounded long-edge) | [blurdetector/decode.py](blurdetector/decode.py) | RAW uses rawpy; prefers embedded JPEG thumbs for speed. |
| EXIF extraction (time, camera, lens, GPS, flash) | [blurdetector/exif.py](blurdetector/exif.py) | Pillow + GPSInfo parsing, rawpy fallback. |
| Sharpness (Laplacian + Tenengrad + FFT anisotropy) | [blurdetector/metrics/sharpness.py](blurdetector/metrics/sharpness.py) | Optional bbox restricts to subject. |
| Subject detection (MediaPipe face + saliency fallback) | [blurdetector/metrics/subject.py](blurdetector/metrics/subject.py) | First subject = primary, drives subject-aware sharpness. |
| Blink / closed-eye (FaceMesh + EAR) | [blurdetector/metrics/eyes.py](blurdetector/metrics/eyes.py) | `CLOSED_THRESHOLD = 0.20`. |
| Exposure (histogram, clipping, dynamic range) | [blurdetector/metrics/exposure.py](blurdetector/metrics/exposure.py) | Flags under/over-exposed. |
| Noise σ (Immerkær) | [blurdetector/metrics/noise.py](blurdetector/metrics/noise.py) | Single fast kernel. |
| Composition (horizon tilt, rule-of-thirds offset) | [blurdetector/metrics/composition.py](blurdetector/metrics/composition.py) | Hough lines + bbox geometry. |
| Perceptual hashes (pHash, dHash) | [blurdetector/metrics/phash.py](blurdetector/metrics/phash.py) | Drives burst grouping. |
| Aesthetic score (NIMA via CoreML) | [blurdetector/metrics/aesthetic.py](blurdetector/metrics/aesthetic.py) | Opt-in via `BLURDETECTOR_NIMA_MODEL` env var; no-op if unset. |
| Decision engine (thresholds, verdict, stars, reasons) | [blurdetector/decide.py](blurdetector/decide.py) | `Thresholds` dataclass is the tunable surface. |
| Burst grouping + best-of-burst pick | [blurdetector/group.py](blurdetector/group.py) | Union-find on pHash hamming within a time window. |
| Time-gap event clustering | [blurdetector/events.py](blurdetector/events.py) | Schema lives in `db.py`. |
| Face clustering (InsightFace `buffalo_s` + greedy cosine) | [blurdetector/face_cluster.py](blurdetector/face_cluster.py) | Optional; no sklearn dep. |
| Offline reverse geocoding | [blurdetector/geocode.py](blurdetector/geocode.py) | Uses `reverse_geocoder` if installed, else hemisphere fallback. |
| Hierarchical organizer (tokens → tree, symlink/move) | [blurdetector/organize.py](blurdetector/organize.py) | All available tokens registered in `TOKENS`. |
| XMP sidecars (rating, label, reasons) | [blurdetector/xmp.py](blurdetector/xmp.py) | Hand-written XML; readable by Lightroom / Bridge / darktable. |
| Static HTML contact-sheet report | [blurdetector/report.py](blurdetector/report.py) | Embeds base64 thumbnails for portability. |
| SQLite schema + helpers (images, metrics, verdicts, bursts, events, faces) | [blurdetector/db.py](blurdetector/db.py) | Metrics stored as JSON for free migrations. |
| Thumbnail cache | [blurdetector/thumb.py](blurdetector/thumb.py) | Content-hash keyed, JPEG q85. |
| Pipeline orchestrator (walk → analyze → persist) | [blurdetector/pipeline.py](blurdetector/pipeline.py) | mtime-based skip; single entry: `analyze_folder`. |
| FastAPI backend (stats, images, ingest, organize, reclassify) | [blurdetector/api.py](blurdetector/api.py) | Mounts `ui/` as static when present. |
| Single-page React UI (Library / Triage / Organize / Settings) | [ui/index.html](ui/index.html) + [ui/app.js](ui/app.js) | esm.sh + Tailwind CDN; no build step. |
| CLI (Typer + Rich) | [blurdetector/cli.py](blurdetector/cli.py) | Commands: `analyze`, `show`, `write-xmp`, `group`, `tokens`, `organize`, `events`, `faces`, `report`, `serve`. |

## Build & test

- **Env**: `uv sync --all-extras`
- **CLI**: `uv run blurdetector <cmd>` (or `uv run python -m blurdetector.cli`)
- **API + UI**: `uv run blurdetector serve` → http://127.0.0.1:8765
- **Tests**: `uv run pytest` (`-k name` for a single test)
- **Lint / format**: `uv run ruff check` · `uv run ruff format`

## Conventions for changes

- **Execution**: always `uv run …`; never bare `python` / `python3`.
- **Style**: snake_case fns/vars, PascalCase classes. Surgical edits — touch only what's asked, preserve nearby comments/docstrings.
- **Comments**: WHY-only when non-obvious. No filler, no decorative banners, no per-task narration in code.
- **Markdown**: don't generate reports unless explicitly requested.
- **Persistence model**: add new metrics under the JSON blob in `metrics`; promote to a dedicated column only when you need to index/filter on it.
- **Organizer tokens**: pure `(record) → str`; register in `TOKENS`. "/"-joined returns nest automatically.
- **Heavy deps** (rawpy, mediapipe, insightface, coremltools): keep imports inside the function that uses them so the rest of the package imports without them.
