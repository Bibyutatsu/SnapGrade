# SnapGrade — Agent Index

A privacy-respecting, fully-local utility that culls and organizes photo libraries on an 8 GB MacBook Air. Built from classical CV + a few tiny purpose-built models (no large transformers / VLMs). The full design rationale lives in `/Users/oindrila/.claude/plans/i-want-you-to-polymorphic-seal.md` — read it before redesigning any layer.

## Mental model

Three decoupled layers; any one can be swapped without disturbing the others:

1. **Analyzer** — pure `image → metrics` functions. Stateless, cacheable.
2. **Decision engine** — `(metrics, thresholds) → verdict + stars + reasons`.
3. **Organizer / UI** — reads the SQLite cache, drives the UI, writes XMP sidecars, builds the user-defined hierarchical tree.

Single source of truth: `~/.snapgrade/library.db` (SQLite, WAL). Files on disk are never authoritative — re-runs are idempotent. Thumbnails cached at `~/.snapgrade/thumbs/`.

## Where things live

| Concern | File | Notes |
|---|---|---|
| Image decoding (RAW / HEIC / JPEG, bounded long-edge) | [snapgrade/decode.py](snapgrade/decode.py) | RAW uses rawpy; prefers embedded JPEG thumbs for speed. |
| EXIF extraction (time, camera, lens, GPS, flash) | [snapgrade/exif.py](snapgrade/exif.py) | Pillow + GPSInfo parsing, rawpy fallback. |
| Sharpness (Laplacian + Tenengrad + FFT anisotropy) | [snapgrade/metrics/sharpness.py](snapgrade/metrics/sharpness.py) | Optional bbox restricts to subject. |
| Subject detection (MediaPipe face + saliency fallback) | [snapgrade/metrics/subject.py](snapgrade/metrics/subject.py) | First subject = primary, drives subject-aware sharpness. |
| Blink / closed-eye + expression (FaceLandmarker blendshapes + EAR) | [snapgrade/metrics/face_expression.py](snapgrade/metrics/face_expression.py) | `CLOSED_EAR_THRESHOLD = 0.20`. |
| Exposure (histogram, clipping, dynamic range) | [snapgrade/metrics/exposure.py](snapgrade/metrics/exposure.py) | Flags under/over-exposed. |
| Noise σ (Immerkær) | [snapgrade/metrics/noise.py](snapgrade/metrics/noise.py) | Single fast kernel. |
| Composition (horizon tilt, rule-of-thirds offset) | [snapgrade/metrics/composition.py](snapgrade/metrics/composition.py) | Hough lines + bbox geometry. |
| Perceptual hashes (pHash, dHash) | [snapgrade/metrics/phash.py](snapgrade/metrics/phash.py) | Drives burst grouping. |
| Aesthetic score (NIMA via CoreML) | [snapgrade/metrics/aesthetic.py](snapgrade/metrics/aesthetic.py) | Opt-in via `SNAPGRADE_NIMA_MODEL` env var; no-op if unset. |
| Decision engine (thresholds, verdict, stars, reasons) | [snapgrade/decide.py](snapgrade/decide.py) | `Thresholds` dataclass is the tunable surface. |
| Burst grouping + best-of-burst pick | [snapgrade/group.py](snapgrade/group.py) | Union-find on pHash hamming within a time window. |
| Time-gap event clustering | [snapgrade/events.py](snapgrade/events.py) | Schema lives in `db.py`. |
| Face clustering (InsightFace `buffalo_s` + greedy cosine) | [snapgrade/face_cluster.py](snapgrade/face_cluster.py) | Optional; no sklearn dep. |
| Offline reverse geocoding | [snapgrade/geocode.py](snapgrade/geocode.py) | Uses `reverse_geocoder` if installed, else hemisphere fallback. |
| Hierarchical organizer (tokens → tree, symlink/move) | [snapgrade/organize.py](snapgrade/organize.py) | All available tokens registered in `TOKENS`. |
| XMP sidecars (rating, label, reasons) | [snapgrade/xmp.py](snapgrade/xmp.py) | Hand-written XML; readable by Lightroom / Bridge / darktable. |
| Static HTML contact-sheet report | [snapgrade/report.py](snapgrade/report.py) | Embeds base64 thumbnails for portability. |
| SQLite schema + helpers (images, metrics, verdicts, bursts, events, faces) | [snapgrade/db.py](snapgrade/db.py) | Metrics stored as JSON for free migrations. |
| Thumbnail cache | [snapgrade/thumb.py](snapgrade/thumb.py) | Content-hash keyed, JPEG q85. |
| Pipeline orchestrator (walk → analyze → persist) | [snapgrade/pipeline.py](snapgrade/pipeline.py) | mtime-based skip; single entry: `analyze_folder`. |
| FastAPI backend (stats, images, ingest, organize, reclassify) | [snapgrade/api.py](snapgrade/api.py) | Mounts `ui/` as static when present. |
| Single-page React UI (Library / Triage / Organize / Settings) | [ui/index.html](ui/index.html) + [ui/app.js](ui/app.js) | esm.sh + Tailwind CDN; no build step. |
| CLI (Typer + Rich) | [snapgrade/cli.py](snapgrade/cli.py) | Commands: `analyze`, `show`, `write-xmp`, `group`, `tokens`, `organize`, `events`, `faces`, `report`, `serve`. |

## Build & test

- **Env**: `uv sync --all-extras`
- **CLI**: `uv run snapgrade <cmd>` (or `uv run python -m snapgrade.cli`)
- **API + UI**: `uv run snapgrade serve` → http://127.0.0.1:8765
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
