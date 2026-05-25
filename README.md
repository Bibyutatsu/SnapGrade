<div align="center">

```text
   _____                   ______                __  
  / ___/____  ____ _____  / ____/________ ______/ /__
  \__ \/ __ \/ __ `/ __ \/ / __/ ___/ __ `/ __  / _ \
 ___/ / / / / /_/ / /_/ / /_/ / /  / /_/ / /_/ /  __/
/____/_/ /_/\__,_/ .___/\____/_/   \__,_/\__,_|\___/ 
                /_/                                  
```

**Local, privacy-respecting photo triage and organizer.**

*Detects blur, closed eyes, exposure issues, groups bursts, clusters faces, searches by visual semantics, and organizes folders by EXIF + quality.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)](pyproject.toml)
[![Astral UV](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

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

## Model Weights

SnapGrade uses small, local model checkpoints. Run the setup command to fetch optional weights from the community host [`Bibyutatsu/macos-computer-vision-models`](https://github.com/Bibyutatsu/macos-computer-vision-models) or download them on demand from the **Library** screen in the web UI.

```bash
uv run snapgrade setup
```

| Model | Feature | Size | Obtained by |
|---|---|---|---|
| YuNet (ONNX) | Face detection | ~400 KB | **Auto** on first analyze |
| MediaPipe FaceLandmarker | Blink / closed-eye (EAR) | ~2 MB | **Auto** on first analyze |
| InsightFace `buffalo_s` | Face clustering & embedding | ~17 MB | **Auto** by InsightFace on first `faces` run |
| U²-Netp (ONNX) | Salient subject segmentation | ~4.5 MB | `setup` / UI button |
| YOLOv8n (CoreML) | Object detection & person bboxes | ~6 MB | `setup` / UI button |
| HyperIQA (CoreML) | Enhanced aesthetic scoring | ~8 MB | `setup` / UI button |
| MobileCLIP (ONNX) | Semantic search embeddings | ~25 MB | `setup` / UI button |
| Places365 (CoreML) | Scene classification | ~20 MB | `setup` / UI button |
| Subject segmentation (CoreML) | Precise framing masks | ~4 MB | `setup` / UI button |
| Depth estimation (CoreML) | Depth map analysis | ~6 MB | `setup` / UI button |
| screendoc (CoreML) | Document/Screenshot detection | ~3 MB | `setup` / UI button |

---

## Quickstart

```bash
# Analyze a folder (recursively logs metrics to sqlite cache)
uv run snapgrade analyze /path/to/photos

# Group burst sequences
uv run snapgrade group --hamming 10 --seconds 3

# Start the web UI + API server
uv run snapgrade serve
# → Open http://127.0.0.1:8765 in your browser
```

---

## CLI Reference

| Command | Description |
|---|---|
| `analyze <folder>` | Recursively analyze, compute metrics, and store in SQLite |
| `show <folder>` | Print cached verdicts without re-analyzing |
| `write-xmp <folder>` | Export XMP sidecars containing ratings/labels |
| `group` | Group burst sequences by perceptual hash + timestamp |
| `events` | Cluster images into shooting sessions by time gap |
| `faces` | Cluster detected faces (requires `insightface`) |
| `organize` | Restructure files using EXIF + quality template tokens |
| `tokens` | List all available organizer tokens |
| `report` | Generate static HTML contact sheet reports |
| `serve` | Start the local FastAPI server and React UI |
| `setup` | Download and verify all optional model weights |

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SNAPGRADE_MODELS_DIR` | `~/.snapgrade/models` | Override model cache directory |
| `SNAPGRADE_YOLO_MODEL` | `~/.snapgrade/models/yolov8n.onnx` | Custom YOLOv8n path |
| `SNAPGRADE_U2NETP_MODEL` | `~/.snapgrade/models/u2netp.onnx` | Custom U²-Netp path |
| `SNAPGRADE_HYPERIQA_MODEL` | `~/.snapgrade/models/hyperiqa.mlpackage` | Path to HyperIQA aesthetic scoring model |
| `SNAPGRADE_MOBILECLIP_MODEL` | `~/.snapgrade/models/mobileclip.onnx` | Path to MobileCLIP semantic embedding model |
| `SNAPGRADE_DEPTH_MODEL` | `~/.snapgrade/models/depth.mlpackage` | Path to depth estimation model |
| `SNAPGRADE_SUBJECT_SEG_MODEL` | `~/.snapgrade/models/subject_seg.mlpackage` | Path to subject segmentation model |
| `SNAPGRADE_SCENE_MODEL` | `~/.snapgrade/models/places365.mlpackage` | Custom Places365 path |
| `SNAPGRADE_SCREENDOC_MODEL` | `~/.snapgrade/models/screendoc.mlpackage` | Custom screenshot/document path |
| `SNAPGRADE_ENABLE_SEMANTIC` | unset | Set to `1` to enable MobileCLIP embeddings indexing |

---

## License

[MIT](LICENSE)
