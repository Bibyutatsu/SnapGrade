"""Object detector via YOLO26n (CoreML or ONNX, ~10 MB, COCO 80 classes).

Prefers ~/.snapgrade/models/yolo26n.mlpackage, falls back to yolo26n.onnx.
Override the path with SNAPGRADE_YOLO_MODEL. Optional labels file
(yolo26n_labels.txt) defaults to the canonical COCO 80 list when missing.

YOLO26 is exported NMS-free: outputs are already-decoded [N, 6] boxes
(xyxy + score + class_id), so no NMS step here.

Returns: list of top detections (class, confidence, bbox) + primary class.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_IN_SIZE = 640
_CONF_TH = 0.35

_COCO80 = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake",
    "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop",
    "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
]


def _model_path() -> Path | None:
    p = os.environ.get("SNAPGRADE_YOLO_MODEL")
    if p and Path(p).exists():
        return Path(p)
    models_dir = Path.home() / ".snapgrade" / "models"
    for candidate in (
        models_dir / "yolo26n.mlpackage",
        models_dir / "yolo26n.onnx",
    ):
        if candidate.exists():
            return candidate
    return None


def is_available() -> bool:
    return _model_path() is not None


_MODEL = None
_LOADED = False
_IS_COREML = False
_LABELS: list[str] | None = None


def _load() -> Any | None:
    global _MODEL, _LOADED, _IS_COREML, _LABELS
    if _LOADED:
        return _MODEL
    _LOADED = True
    mp = _model_path()
    if not mp:
        return None
    try:
        is_cml = mp.suffix == ".mlpackage" or mp.is_dir()
        if is_cml:
            from .. import models as _m
            _MODEL = _m.load_coreml(mp)
            _IS_COREML = True
        else:
            import onnxruntime as ort
            _MODEL = ort.InferenceSession(str(mp), providers=["CPUExecutionProvider"])
            _IS_COREML = False

        labels_file = mp.parent / "yolo26n_labels.txt"
        if labels_file.exists():
            _LABELS = [ln.strip() for ln in labels_file.read_text().splitlines() if ln.strip()]
        else:
            _LABELS = list(_COCO80)
    except Exception:
        _MODEL = None
    return _MODEL


def analyze(rgb: np.ndarray) -> dict[str, Any]:
    model = _load()
    if model is None:
        return {}
    try:
        h0, w0 = rgb.shape[:2]
        scale = _IN_SIZE / max(h0, w0)
        nw, nh = int(w0 * scale), int(h0 * scale)
        im = Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR)
        labels = _LABELS or _COCO80

        if _IS_COREML:
            # YOLO26n CoreML is NMS-free: output is [1,300,6] = xyxy + score + class_id,
            # same layout as the ONNX path below. No PIL conversion or threshold inputs.
            canvas = np.zeros((_IN_SIZE, _IN_SIZE, 3), dtype=np.float32)
            canvas[:nh, :nw] = np.asarray(im, dtype=np.float32) / 255.0
            x = canvas.transpose(2, 0, 1)[None, ...].astype(np.float32)
            out = model.predict({"images": x})
            pred = list(out.values())[0][0]  # [300, 6]
            dets = []
            for x0, y0, x1, y1, score, cls in pred:
                if score < _CONF_TH:
                    continue
                ci = int(cls)
                dets.append({
                    "class": labels[ci] if ci < len(labels) else str(ci),
                    "conf": float(score),
                    "bbox": [int(x0 / scale), int(y0 / scale), int(x1 / scale), int(y1 / scale)],
                })
            dets.sort(key=lambda d: -d["conf"])
            return {"detections": dets[:10], "primary": dets[0]["class"] if dets else None}

        else:
            canvas = np.zeros((_IN_SIZE, _IN_SIZE, 3), dtype=np.float32)
            canvas[:nh, :nw] = np.asarray(im, dtype=np.float32) / 255.0
            x = canvas.transpose(2, 0, 1)[None, ...].astype(np.float32)
            out = model.run(None, {model.get_inputs()[0].name: x})[0]
            pred = np.asarray(out)
            if pred.ndim == 3:
                pred = pred[0]
            # YOLO26 NMS-free export: [N, 6] = xyxy + score + class_id.
            if pred.ndim != 2 or pred.shape[1] != 6:
                return {}
            dets = []
            for x0, y0, x1, y1, score, cls in pred:
                if score < _CONF_TH:
                    continue
                ci = int(cls)
                dets.append({
                    "class": labels[ci] if ci < len(labels) else str(ci),
                    "conf": float(score),
                    "bbox": [int(x0 / scale), int(y0 / scale), int(x1 / scale), int(y1 / scale)],
                })
            dets.sort(key=lambda d: -d["conf"])
            return {"detections": dets[:10], "primary": dets[0]["class"] if dets else None}
    except Exception:
        return {}
