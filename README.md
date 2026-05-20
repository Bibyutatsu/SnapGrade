# SnapGrade

Local, privacy-respecting photo triage and organizer. Detects blur, out-of-focus subjects, closed eyes, exposure problems; groups bursts; organizes folders by EXIF + quality. Designed to run comfortably on a MacBook Air with 8 GB RAM — classical CV plus tiny purpose-built models, no large transformers.

## Status

Phase 1 (analyzer + CLI) in progress.

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

### 2. Clone and install

```bash
git clone https://github.com/Bibyutatsu/SnapGrade.git
cd SnapGrade
uv sync --all-extras
```

This installs the core package plus all optional extras (API server, dev tools).

### 3. Verify

```bash
uv run snapgrade --help
```

---

## Model Weights

SnapGrade uses several small models for different analysis tasks. **`uv sync` installs the Python packages, not the model weights** — weights are fetched separately (once) from the community model host [`Bibyutatsu/macos-computer-vision-models`](https://github.com/Bibyutatsu/macos-computer-vision-models).

### Fastest path — one command

```bash
uv run snapgrade setup
```

This downloads every optional model (U²-Netp, YOLOv8n CoreML, NIMA, Places365 + labels, screendoc) into `~/.snapgrade/models/`. YuNet + MediaPipe FaceLandmarker are *not* included — they auto-download on first `analyze`. Use `--only u2netp,yolov8n` for a subset, `--force` to re-download.

You can also download each model on demand from the **Library tab** in the web UI (a "Download" button appears next to any model whose weights are missing).

| Model | Feature | Size | Obtained by |
|---|---|---|---|
| YuNet (ONNX) | Face detection | ~400 KB | **Auto** on first analyze |
| MediaPipe FaceLandmarker | Blink / closed-eye (EAR) | ~2 MB | **Auto** on first analyze |
| InsightFace `buffalo_s` | Face clustering | ~17 MB | **Auto** by InsightFace on first `faces` run |
| U²-Netp (ONNX) | Salient subject segmentation — picks the foreground subject in crowds, recovers hair/scarf-occluded subjects | ~4.5 MB | `setup` / UI button |
| YOLOv8n (CoreML, baked-in NMS) | Object detection; feeds the subject picker via `person` bboxes | ~6 MB | `setup` / UI button |
| NIMA (CoreML) | Aesthetic scoring | ~14 MB | `setup` / UI button |
| Places365 (CoreML) | Scene classifier (adds `scene` organizer token) | ~20 MB | `setup` / UI button (pulls labels too) |
| screendoc (CoreML) | Screenshot / document detection | ~3 MB | `setup` / UI button. Falls back to a palette/saturation heuristic when absent. |

Weights are cached to `~/.snapgrade/models/`. Override the cache dir with `SNAPGRADE_MODELS_DIR`, or point at a fork/mirror of the model host with `SNAPGRADE_MODELS_REPO`.

The optional models are **opt-in per library**: the Library tab's ingest dialog shows a checkbox for each model whose weights are present. Your selection is recorded against the library, so re-ingest and per-library Sync only run what was selected.

> **Note on screendoc:** the currently hosted model is trained on synthetic "photo" samples and over-fires on real DSLR shots, so its output is stored as a metric but **does not affect verdicts** (gated at conf ≥ 0.90 and never used to reject). Retrain the `photo` class on real photos in the model-host repo to make it verdict-grade.

---

### U²-Netp — salient subject segmentation (recommended)

Used to distinguish a foreground subject from a background crowd, and to recover a subject when the face detector misses (sunglasses / occluded face / back-of-head). When unavailable, the engine falls back to a pure face-size cluster heuristic.

Easiest path — click **Download** next to "Salient subject seg" on the Library tab.

Manual:

```bash
mkdir -p ~/.snapgrade/models
curl -L "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx" \
     -o ~/.snapgrade/models/u2netp.onnx
```

Custom path:

```bash
export SNAPGRADE_U2NETP_MODEL=/path/to/u2netp.onnx
```

---

### YOLOv8n — object detection (optional)

Adds COCO class detections (person / pet / food / vehicle / etc.) used both as organizer tokens (`object:class`) and as a secondary "is this face the foreground subject?" signal.

**The Ultralytics releases page does not ship a pre-built ONNX** — `https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.onnx` returns 404. Export from the published `.pt` checkpoint instead (the `ultralytics` package is already in the project's optional deps):

```bash
uv add ultralytics            # one-time, if not already installed
uv run python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"
mv yolov8n.onnx ~/.snapgrade/models/
```

`YOLO('yolov8n.pt')` auto-fetches the .pt weights from Ultralytics on first run (~6 MB). The exported ONNX is ~12 MB.

Custom path:

```bash
export SNAPGRADE_YOLO_MODEL=/path/to/yolov8n.onnx
```

---

### InsightFace `buffalo_s` — face clustering (optional)

First install the Python package:

```bash
uv add insightface
```

Then run the `faces` command — InsightFace downloads `buffalo_s` automatically on the first call:

```bash
uv run snapgrade faces --db ~/.snapgrade/library.db
```

The pack (~17 MB) is saved to `~/.insightface/models/buffalo_s/`.

---

### NIMA — aesthetic scoring (optional, macOS only)

NIMA ranks photos by perceived aesthetic quality. No pre-built CoreML file is publicly distributed, but converting a PyTorch checkpoint is a one-time step.

#### Step 1 — install conversion dependencies

```bash
uv add torch torchvision coremltools
```

#### Step 2 — download a pre-trained NIMA checkpoint

The [`titu1994/neural-image-assessment`](https://github.com/titu1994/neural-image-assessment) repo provides MobileNet and InceptionV2 checkpoints trained on the AVA dataset. Download a `.pth` file from its releases page, for example `epoch-82.pth` (MobileNet backbone).

#### Step 3 — convert to CoreML

Save the following as `convert_nima.py` at the repo root and run it once:

```python
# convert_nima.py
import torch
import coremltools as ct
from torchvision.models import mobilenet_v2

# Load the architecture and checkpoint
model = mobilenet_v2(weights=None)
model.classifier[1] = torch.nn.Linear(model.last_channel, 10)  # 10-bin NIMA head
state = torch.load("epoch-82.pth", map_location="cpu")
model.load_state_dict(state)
model.eval()

# Trace and convert
example = torch.zeros(1, 3, 224, 224)
traced = torch.jit.trace(model, example)
mlmodel = ct.convert(
    traced,
    inputs=[ct.TensorType(name="input", shape=example.shape)],
)
mlmodel.save("nima.mlpackage")
print("Saved nima.mlpackage")
```

```bash
uv run python convert_nima.py
```

#### Step 4 — point SnapGrade at the model

```bash
export SNAPGRADE_NIMA_MODEL="$(pwd)/nima.mlpackage"
```

Add that export to your shell profile (`~/.zshrc`) to make it permanent. If the variable is unset, aesthetic scoring is silently skipped and all other analysis continues normally.

---

## Quickstart

```bash
# Analyze a folder (auto-downloads YuNet + FaceLandmarker on first run)
uv run snapgrade analyze /path/to/photos

# Show cached verdicts without re-analyzing
uv run snapgrade show /path/to/photos

# Write XMP sidecars (ratings/labels readable by Lightroom, darktable, Bridge)
uv run snapgrade write-xmp /path/to/photos

# Start the web UI + API
uv run snapgrade serve
# → http://127.0.0.1:8765
```

---

## CLI Reference

| Command | Description |
|---|---|
| `analyze <folder>` | Recursively analyze, store results in `~/.snapgrade/library.db` |
| `show <folder>` | Re-print cached verdicts without re-analyzing |
| `write-xmp <folder>` | Emit XMP sidecars with ratings and labels |
| `group` | Group burst sequences by perceptual hash + timestamp |
| `events` | Cluster images into time-gap events |
| `faces` | Detect and cluster faces across the library (requires `insightface`) |
| `organize` | Build a folder tree / symlink hierarchy from EXIF + quality tokens |
| `tokens` | List all available organizer tokens |
| `report` | Generate a static HTML contact-sheet report |
| `serve` | Start the FastAPI backend + React UI on port 8765 |

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SNAPGRADE_MODELS_DIR` | `~/.snapgrade/models` | Override model cache directory |
| `SNAPGRADE_YOLO_MODEL` | `~/.snapgrade/models/yolov8n.onnx` | Custom YOLOv8n path |
| `SNAPGRADE_U2NETP_MODEL` | `~/.snapgrade/models/u2netp.onnx` | Custom U²-Netp path |
| `SNAPGRADE_NIMA_MODEL` | `~/.snapgrade/models/nima.mlpackage` (auto-detected) | Path to NIMA `.mlpackage` / `.mlmodelc`. If unset and the default file is missing, aesthetic scoring is skipped. |
| `SNAPGRADE_SCENE_MODEL` | `~/.snapgrade/models/places365.mlpackage` | Custom Places365 path |
| `SNAPGRADE_SCENE_LABELS` | `~/.snapgrade/models/places365_labels.txt` | Newline-separated Places365 class labels |
| `SNAPGRADE_SCREENDOC_MODEL` | `~/.snapgrade/models/screendoc.mlpackage` | Custom screenshot/document head path |

## Runtime dependencies for optional models

The base install runs the analyzer with only YuNet + MediaPipe. Each optional model brings its own runtime:

| Model | Extra package | Install |
|---|---|---|
| U²-Netp, YOLOv8n (ONNX) | `onnxruntime` | `uv add onnxruntime` |
| NIMA, Places365, screendoc (CoreML) | `coremltools` | `uv add coremltools` (already pulled in by the NIMA conversion step) |
| InsightFace `buffalo_s` | `insightface` | `uv add insightface` |
| YOLOv8n export from `.pt` | `ultralytics` | `uv add ultralytics` (one-time, for the conversion only) |
