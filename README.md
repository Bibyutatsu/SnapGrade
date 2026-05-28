<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/banner_dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="docs/images/banner_light.svg">
    <img alt="SnapGrade Banner" src="docs/images/banner.svg" width="100%" />
  </picture>
</div>

<div align="center">

**Local, privacy-respecting photo triage and organizer.**

*Detects blur, closed eyes, exposure issues, groups bursts, clusters faces, searches by visual semantics, and organizes folders by EXIF + quality.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)](pyproject.toml)
[![Astral UV](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Download macOS App](https://img.shields.io/badge/Download-macOS%20App%20v0.2.0-blue?logo=apple&logoColor=white)](https://github.com/Bibyutatsu/SnapGrade/releases/download/v0.2.0/SnapGrade-macOS.dmg)

<br/>
<img src="docs/images/triage.png" alt="SnapGrade Contact Sheet" width="90%" style="border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);" />
</div>

---

## Status

SnapGrade is ready for local culling workflows. It provides a FastAPI analyzer backend, SQLite metrics cache, CLI commands, and a React-based web dashboard. It features real-time face clustering, burst grouping, visual semantic search, and configurable quality thresholds.

---

## Features & Visual Walkthrough

### 1. Interactive Contact Sheet & Triage (Web UI)
* **Grid vs. Filmstrip Layouts**: Switch between a dense contact sheet for rapid scanning, and Filmstrip mode (large hero image with bottom thumbnail strip) for fast arrow-key evaluation.
* **Calibrated Themes**: Choose between *Film Lab* (warm amber dark mode), *Modern* (cool dark grey), and *Light Pro* (high-contrast light mode) to suit your editing suite's lighting conditions.

<div align="center">
  <img src="docs/images/filmstrip.png" alt="Filmstrip Mode" width="48%" style="border-radius: 6px;" />
  <img src="docs/images/triage_filters.png" alt="Triage Filters" width="48%" style="border-radius: 6px;" />
</div>

---

### 2. Sharpness & Subject-Aware Detection
* **Three Sharpness Signals**: Combines Laplacian variance, Tenengrad gradient energy, and FFT directional energy to distinguish camera shake from out-of-focus blur.
* **Subject-Aware Focus**: Restricts sharpness analysis to detected subjects (using MediaPipe face landmarking or salient subject segmentation fallbacks) to avoid penalizing artistic background bokeh.

<div align="center">
  <img src="docs/images/subject_bboxes.png" alt="Subject Bounding Boxes" width="60%" style="border-radius: 6px;" />
</div>

---

### 3. Burst Management (Best-of-Burst)
* **Union-Find Grouping**: Automatically identifies and groups near-duplicate burst sequences using 64-bit perceptual hashes and timestamp proximity.
* **Best-of-Burst Selection**: Ranks frames within a group based on a composite quality score (sharpness, smile, exposure, open eyes) and highlights the best candidate.

<div align="center">
  <img src="docs/images/bursts.png" alt="Burst Management" width="70%" style="border-radius: 6px;" />
</div>

---

### 4. Face Detection & Clustering
* **Cosine Similarity Grouping**: Clusters detected faces using InsightFace `buffalo_s` embeddings.
* **Person Cards**: Generates cluster cards for every detected individual in the library, allowing single-click filtering of all images featuring that person.

<div align="center">
  <img src="docs/images/faces.png" alt="Face Clusters" width="70%" style="border-radius: 6px;" />
</div>

---

### 5. Hierarchical Organization & XMP Export
* **Custom Folder Templates**: Structure your output folder tree using metadata tokens (e.g., `{date:YYYY}/{camera_model}/{quality:verdict}`). Supports symbolic links or copy/move operations.
* **Lightroom Compatibility**: Write verdicts, ratings (1–5 stars), and rejection reasons to industry-standard XMP sidecars that Lightroom, darktable, and Bridge read automatically.

<div align="center">
  <img src="docs/images/organize.png" alt="Folder Templates" width="48%" style="border-radius: 6px;" />
  <img src="docs/images/xmp_export.png" alt="XMP Export" width="48%" style="border-radius: 6px;" />
</div>

---

## Installation

### 1. Prerequisites
- macOS (Apple Silicon or Intel)
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) — fast Python package manager

Install `uv` if you don't have it:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and Install
```bash
git clone https://github.com/Bibyutatsu/SnapGrade.git
cd SnapGrade
uv sync --all-extras
```

### 3. Verify
```bash
uv run snapgrade --help
```
---

## macOS Standalone Desktop App

> **[⬇ Download SnapGrade-macOS.dmg (v0.2.0)](https://github.com/Bibyutatsu/SnapGrade/releases/download/v0.2.0/SnapGrade-macOS.dmg)**  
> No Python or `uv` required — open the `.dmg`, drag **SnapGrade** to Applications, then launch it.

The app bundles the full Python backend as a sidecar binary and serves the web UI locally. On first launch, use **SnapGrade → Install Command Line Tool…** from the menu bar to make the `snapgrade` CLI available globally in your terminal.

For local compilation, `.dmg` packaging, and CI/CD release details see the [macOS Desktop App Guide](docs/macos_desktop.md).

---

## Documentation

For advanced setup, CLI usage, models registry, and configuration options, see:
- [SnapGrade Complete Guide & Reference](docs/guide.md) — Comprehensive guide to CLI commands, models, quickstart, and environment variables
- [Brand & UI Design System](docs/DESIGN.md) — UI theme colors and visual guidelines

---

## License

[MIT](LICENSE)
