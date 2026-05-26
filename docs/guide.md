# SnapGrade Complete User Guide & Reference

This guide provides a comprehensive walkthrough, CLI command reference, model checkpoint registry, and configuration options for SnapGrade.

---

## 1. Quickstart Guide

This section helps you set up and run common triage tasks.

### Installation Check
Make sure you have synchronized the Python virtual environment with optional extras (required for face clustering and image processing models):
```bash
uv sync --all-extras
```
Verify the installation by running the help command:
```bash
uv run snapgrade --help
```

### Typical Workflow Example

1. **Setup optional models**:
   If you have an Apple Silicon Mac, download optimized CoreML weights for aesthetic scoring, semantic search, depth analysis, and object detection:
   ```bash
   uv run snapgrade setup
   ```
2. **Analyze a photo directory**:
   Scan a folder of photos (supports JPEG, RAW, and HEIC). This computes sharpness, subject-aware focus, face expression blendshapes, noise, exposure, and composition metrics:
   ```bash
   uv run snapgrade analyze /path/to/photos --models scene,objects
   ```
   *Note: Under the hood, this writes all computed image metrics and sorting verdicts into a local SQLite database (`~/.snapgrade/library.db`).*

3. **Group bursts (Action/Action Sequences)**:
   Burst sequences are grouped automatically based on perceptual hashing (pHash) and the time delta between frames. The best candidate is selected based on eye openness, smile/expression, exposure correctness, and subject sharpness:
   ```bash
   uv run snapgrade group --hamming 10 --seconds 3
   ```

4. **Cluster faces**:
   Run face detection and group people across your entire library using InsightFace:
   ```bash
   uv run snapgrade faces --detect --cluster
   ```

5. **Start the interactive UI**:
   Launch the FastAPI backend and web application dashboard:
   ```bash
   uv run snapgrade serve
   ```
   Now visit [http://127.0.0.1:8765](http://127.0.0.1:8765) in your web browser.

---

## 2. CLI Command Reference

SnapGrade exposes the following subcommands through its Typer-based CLI.

### `analyze <folder>`
Analyze all photos in `<folder>` and write metrics/verdicts to the SQLite library cache.

*   **Arguments**:
    *   `folder` (Required): Path to the image folder.
*   **Options**:
    *   `--db <path>`: SQLite database path (default: `~/.snapgrade/library.db`).
    *   `--force`: Re-run analysis even if the file is already cached (default: `False`).
    *   `--max-edge <int>`: Long-edge dimension to resize images to for inference (default: `2000`).
    *   `--workers <int>`: Number of parallel worker threads (default: `0` for auto-detect).
    *   `--models <string>`: Comma-separated list of opt-in models to run (e.g., `scene,objects,depth,subject_seg,content_type`). Note: `ocr` is an alias for `content_type` that forces OCR text extraction and indexing.

### `show <folder>`
Output previously cached verdicts and quality stats for the files under `<folder>` without executing any new analysis.

*   **Arguments**:
    *   `folder` (Required): Path to the folder.
*   **Options**:
    *   `--db <path>`: Database location.

### `write-xmp <folder>`
Export sorting verdicts (e.g., *keeper*, *review*, *reject*), ratings (1 to 5 stars), and analysis reasons into industry-standard sidecar XML (`.xmp`) files next to the original images. These are automatically parsed by Adobe Lightroom, darktable, and Bridge.

*   **Arguments**:
    *   `folder` (Required): Path to the folder.
*   **Options**:
    *   `--db <path>`: Database location.

### `group`
Group near-duplicate photos / burst sequences and mark the single best candidate.

*   **Options**:
    *   `--db <path>`: Database location.
    *   `--hamming <int>`: Maximum Hamming distance of pHash/dHash values to merge frames (default: `10`).
    *   `--seconds <int>`: Maximum capture time gap (in seconds) between sequential frames to keep them in the same burst (default: `3`).
    *   `--library-id <int>`: Restrict burst grouping to a specific folder id in the DB.

### `events`
Automatically cluster photos into "events" (shooting sessions) based on capture time gaps.

*   **Options**:
    *   `--db <path>`: Database location.
    *   `--gap-hours <float>`: Time gap threshold in hours to split shooting events (default: `6.0`).

### `faces`
Detect faces and cluster them into identity groups across the entire library.

*   **Options**:
    *   `--db <path>`: Database location.
    *   `--detect / --no-detect`: Run face detection to extract embeddings (default: `True`).
    *   `--cluster / --no-cluster`: Perform identity clustering (default: `True`).
    *   `--incremental`: Perform incremental clustering — attach new face detections to existing cluster groups rather than rebuilding clusters from scratch (default: `False`).
    *   `--threshold <float>`: Cosine similarity cutoff threshold for matching identity embeddings (default: `0.30`).

### `organize <root>`
Dry-run or apply automated catalog structure organization based on EXIF and quality metadata.

*   **Arguments**:
    *   `root` (Required unless `--undo`): Destination folder root.
*   **Options**:
    *   `-l, --level <string>` (Required unless `--undo`): Token key specifying a folder path hierarchy level. Repeat for multi-level nesting (e.g., `-l date:YYYY -l camera_model -l quality:verdict`).
    *   `--db <path>`: Database location.
    *   `--mode <string>`: File copy mechanism: `symlink` (default), `hardlink`, `copy`, or `move`.
    *   `--apply`: Actually perform the operations (omitting this runs a dry-run preview).
    *   `--scope <path>`: Restrict catalog structure organizing to files under this directory.
    *   `--undo`: Reverse the effects (file moves/links) of the single most recent organize action.

### `tokens`
Print all registered tokens available for organizing folder templates.

### `report <out>`
Generate an offline-portable HTML contact sheet containing base64 embedded thumbnails, metrics, and quality ratings.

*   **Arguments**:
    *   `out` (Required): Output `.html` path.
*   **Options**:
    *   `--verdict <string>`: Filter results to output: `keeper` (default), `review`, `reject`, or `all`.
    *   `--db <path>`: Database location.

### `gc-thumbs`
Garbage collect orphan thumbnail images in the thumbnail directory that no longer exist in the library.

*   **Options**:
    *   `--db <path>`: Database location.
    *   `--dry-run`: Output a list of files that would be deleted without removing them.

### `serve`
Start the FastAPI server and React SPA UI dashboard.

*   **Options**:
    *   `--host <string>`: Bind IP host address (default: `127.0.0.1`).
    *   `--port <int>`: Port to bind server to (default: `8765`).
    *   `--reload`: Enable automatic server reloading on code changes (default: `False`).

### `setup`
Pre-download the optional neural network weights to avoid demand-based fetch freezes during scanning.

*   **Options**:
    *   `--only <string>`: Comma-separated list of specific models to pre-fetch.
    *   `--force`: Force fresh download and overwrite existing checkpoints (default: `False`).

---

## 3. Model Weights Registry

SnapGrade prefers small, local-only neural models. Standard models (YuNet, FaceLandmarker) are downloaded automatically on the first scan, while other optional models are fetched via `snapgrade setup`.

On macOS (Apple Silicon), SnapGrade loads `.mlpackage` weights to leverage ANE (Apple Neural Engine) hardware acceleration. On other systems, standard `.onnx` fallbacks are utilized.

| Model Reference Name | Target Filename | Acceleration Format | Description & Purpose |
|---|---|---|---|
| `yunet` | `face_detection_yunet_2023mar.onnx` | ONNX (Inference via OpenCV) | Full-scene face detector, excellent for multiple scales and angles. |
| `yunet_coreml` | `yunet.mlpackage` | CoreML | ANE-optimized version of YuNet. |
| `face_landmarker` | `face_landmarker.task` | MediaPipe Task | 468-point landmarks + blendshapes (blink, smile, frown). Includes EAR (Eye Aspect Ratio). |
| `u2netp_coreml` | `u2netp.mlpackage` | CoreML | ANE-optimized U²-Netp model for salient subject detection. |
| `u2netp` | `u2netp.onnx` | ONNX | Salient subject segmentation fallback. |
| `yolo26n_coreml` | `yolo26n.mlpackage` | CoreML | ANE-optimized YOLOv8n variant for general object bounding boxes (people, pets, etc.). |
| `yolo26n` | `yolo26n.onnx` | ONNX | Object detection fallback. |
| `hyperiqa` | `hyperiqa.mlpackage` | CoreML | ResNet50-backed Aesthetic Score evaluation (No-Reference Image Quality Assessment). |
| `topiq` | `topiq.mlpackage` | CoreML | Alternate ANE-optimized aesthetic scorer. |
| `nima` | `nima.mlpackage` | CoreML | Aesthetic scoring fallback (NIMA network). |
| `depth_coreml` | `depth_anything_v2_small.mlpackage` | CoreML | Depth Anything V2 Small for monocular depth maps to identify focus mismatch. |
| `mobileclip_image` | `mobileclip_s0_image.mlpackage` | CoreML | Apple MobileCLIP-S0 Image embedding encoder for semantic visual search. |
| `mobileclip_text` | `mobileclip_s0_text.mlpackage` | CoreML | Apple MobileCLIP-S0 Text query embedding encoder. |
| `places365` | `places365.mlpackage` | CoreML | Places365 scene classifier (e.g., beach, indoor, sunset). |

### Directory & Verification
*   **Default Cache Directory**: `~/.snapgrade/models/` (can override using environment variables).
*   **Integrity Verification**: SnapGrade verifies downloads against a hardcoded SHA-256 manifest file (`models_manifest.json`) to prevent corrupted or tampered weights from executing.

---

## 4. Environment Variables Configuration

Fine-tune SnapGrade behavior, runtime engines, and folder structures with these configuration variables.

| Variable Name | Default Value | Purpose |
|---|---|---|
| `SNAPGRADE_MODELS_DIR` | `~/.snapgrade/models` | Absolute directory path where neural models are stored. |
| `SNAPGRADE_MODELS_REPO` | `https://raw.githubusercontent.com/...` | Custom raw content base URL mirror for model downloads. |
| `SNAPGRADE_SKIP_CHECKSUM` | `unset` | Set to `1` to bypass SHA-256 verification (useful for dev testing). |
| `SNAPGRADE_COMPUTE_UNITS` | `all` | CoreML execution preference: `all` (ANE -> GPU -> CPU), `cpu_and_gpu`, `cpu_and_neural_engine` (ANE + CPU), or `cpu_only`. |
| `SNAPGRADE_ENABLE_SEMANTIC` | `unset` | Set to `1` to index image features using MobileCLIP for semantic visual searches. |
| `SNAPGRADE_YOLO_MODEL` | `~/.snapgrade/models/yolo26n.mlpackage` | Path override for YOLO model. |
| `SNAPGRADE_U2NETP_MODEL` | `~/.snapgrade/models/u2netp.mlpackage` | Path override for subject segmentation model. |
| `SNAPGRADE_HYPERIQA_MODEL` | `~/.snapgrade/models/hyperiqa.mlpackage` | Path override for aesthetic rating model. |
| `SNAPGRADE_MOBILECLIP_MODEL` | `~/.snapgrade/models/mobileclip_s0_image.mlpackage` | Path override for semantic search model. |
| `SNAPGRADE_DEPTH_MODEL` | `~/.snapgrade/models/depth_anything_v2_small.mlpackage` | Path override for depth estimation model. |
| `SNAPGRADE_SUBJECT_SEG_MODEL` | `~/.snapgrade/models/u2netp.mlpackage` | Path override for subject framing model. |
| `SNAPGRADE_SCENE_MODEL` | `~/.snapgrade/models/places365.mlpackage` | Path override for scene classification model. |
