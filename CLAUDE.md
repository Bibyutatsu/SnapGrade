# BlurDetector: Local Photo Triage & Organizer

Privacy-respecting, fully-local utility for focus/blur detection, blink rejection, burst grouping, and EXIF-driven organization.

## Build & Test Commands
- **Environment Setup**: `uv sync --all-extras`
- **Run CLI**: `uv run python -m blurdetector.cli`
- **Run API (Dev)**: `uv run uvicorn blurdetector.api:app --reload`
- **Run Test Suite**: `uv run pytest`
- **Lint & Format**: `uv run ruff check` / `uv run ruff format`
- **Single Test**: `uv run pytest tests/test_filename.py -k test_name`

## Codebase Index
- `blurdetector/`: Core library package.
  - `metrics/`: Image metric algorithms (sharpness, eye blink, exposure, composition, phash, subject detection).
  - `decode.py`: RAW/HEIC/JPEG image decoding and thumbnail extraction.
  - `exif.py`: EXIF metadata extraction.
  - `db.py`: SQLite cache and library database.
  - `group.py`: Clustering and burst detection.
  - `decide.py`: Triage decision rules engine.
  - `organize.py`: Token-based file organization and linking.
  - `pipeline.py`: Orchestrated thread/process pool execution.
  - `api.py`: FastAPI server endpoints.
  - `cli.py`: Typer command-line interface.
- `ui/`: Vite + React + Tailwind frontend application.

## Coding Standards
- **Karpathy Principles**: Think first (surface assumptions), Simplicity (MV-code), Surgical (match style/str_replace).
- **Python Style**: Use `uv` for management. `snake_case` for functions/vars, `PascalCase` for classes.
- **Python Execution**: Always `uv run python <script>` or `uv run <command>` — never bare `python3` or `python`.
- **Surgical Edits**: Touch only requested lines; preserve comments/docstrings unless requested otherwise.
- **Conciseness**: No filler words. Keep code comments to "WHY" only when non-obvious.
- **No Markdown Artifacts**: Do not generate reports or Markdown docs unless requested.
