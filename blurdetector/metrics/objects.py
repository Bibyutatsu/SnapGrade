"""Object detector via YOLOv8n ONNX (~6 MB, COCO classes).

Drop the model at ~/.blurdetector/models/yolov8n.onnx (or set
BLURDETECTOR_YOLO_MODEL). Optional labels file at yolov8n_labels.txt;
defaults to the canonical COCO 80 list when missing.

Returns: list of top detections (class, confidence, bbox) + primary class.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_SESSION = None
_LOADED = False
_LABELS: list[str] | None = None
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
    p = os.environ.get("BLURDETECTOR_YOLO_MODEL")
    if p and Path(p).exists():
        return Path(p)
    default = Path.home() / ".blurdetector" / "models" / "yolov8n.onnx"
    return default if default.exists() else None


def is_available() -> bool:
    return _model_path() is not None


def _load() -> Any | None:
    global _SESSION, _LOADED, _LABELS
    if _LOADED:
        return _SESSION
    _LOADED = True
    mp = _model_path()
    if not mp:
        return None
    try:
        import onnxruntime as ort
        _SESSION = ort.InferenceSession(str(mp), providers=["CPUExecutionProvider"])
        labels_file = mp.with_name("yolov8n_labels.txt")
        if labels_file.exists():
            _LABELS = [ln.strip() for ln in labels_file.read_text().splitlines() if ln.strip()]
        else:
            _LABELS = list(_COCO80)
    except Exception:
        _SESSION = None
    return _SESSION


def analyze(rgb: np.ndarray) -> dict[str, Any]:
    sess = _load()
    if sess is None:
        return {}
    try:
        h0, w0 = rgb.shape[:2]
        scale = _IN_SIZE / max(h0, w0)
        nw, nh = int(w0 * scale), int(h0 * scale)
        im = Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR)
        canvas = np.zeros((_IN_SIZE, _IN_SIZE, 3), dtype=np.float32)
        canvas[:nh, :nw] = np.asarray(im, dtype=np.float32) / 255.0
        x = canvas.transpose(2, 0, 1)[None, ...].astype(np.float32)
        out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
        # YOLOv8 raw output: [1, 84, 8400]  — 4 box + 80 class scores
        pred = np.asarray(out)[0]
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T  # to [N, 84]
        if pred.shape[1] < 5:
            return {}
        boxes = pred[:, :4]
        scores = pred[:, 4:]
        cls_ids = scores.argmax(axis=1)
        cls_conf = scores.max(axis=1)
        keep = cls_conf >= _CONF_TH
        boxes, cls_ids, cls_conf = boxes[keep], cls_ids[keep], cls_conf[keep]
        labels = _LABELS or _COCO80
        dets = []
        for b, ci, cc in zip(boxes[:50], cls_ids[:50], cls_conf[:50]):
            cx, cy, bw, bh = b.tolist()
            x0 = int((cx - bw / 2) / scale)
            y0 = int((cy - bh / 2) / scale)
            x1 = int((cx + bw / 2) / scale)
            y1 = int((cy + bh / 2) / scale)
            dets.append({
                "class": labels[int(ci)] if int(ci) < len(labels) else str(int(ci)),
                "conf": float(cc),
                "bbox": [x0, y0, x1, y1],
            })
        dets.sort(key=lambda d: d["conf"], reverse=True)
        primary = dets[0]["class"] if dets else None
        return {"detections": dets[:10], "primary": primary}
    except Exception:
        return {}
