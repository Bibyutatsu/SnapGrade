# BlurDetector

Local, privacy-respecting photo triage and organizer. Detects blur, out-of-focus subjects, closed eyes, exposure problems; groups bursts; organizes folders by EXIF + quality. Designed to run comfortably on a MacBook Air with 8 GB RAM — classical CV plus tiny purpose-built models, no large transformers.

## Status

Phase 1 (analyzer + CLI) in progress.

## Quickstart (dev)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
blurdetector analyze /path/to/photos
```

## CLI

- `blurdetector analyze <folder>` — recursively analyze, store results in `~/.blurdetector/library.db`, print verdict table.
- `blurdetector show <folder>` — re-print cached verdicts without re-analyzing.
- `blurdetector write-xmp <folder>` — emit XMP sidecars with ratings/labels from cached verdicts.
