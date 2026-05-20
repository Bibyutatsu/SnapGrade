"""Object detector via YOLO26n ONNX (~10 MB, COCO 80 classes).

Prefers ~/.snapgrade/models/yolo26n.onnx, falling back to the older
yolov8n.{mlpackage,onnx} so existing installs keep working. Override the path
with SNAPGRADE_YOLO_MODEL. Optional labels file (yolo26n_labels.txt or
yolov8n_labels.txt) defaults to the canonical COCO 80 list when missing.

YOLO26 is exported with nms=False, so the raw output keeps YOLOv8's
[1, 84, 8400] layout and the Python NMS below applies unchanged.

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
_IOU_TH = 0.45


def _nms(boxes_xyxy: np.ndarray, scores: np.ndarray, iou_th: float = _IOU_TH) -> list[int]:
    """Standard greedy NMS. Returns indices to keep, sorted by score desc."""
    if boxes_xyxy.size == 0:
        return []
    order = scores.argsort()[::-1].tolist()
    keep: list[int] = []
    x0, y0, x1, y1 = boxes_xyxy[:, 0], boxes_xyxy[:, 1], boxes_xyxy[:, 2], boxes_xyxy[:, 3]
    areas = (x1 - x0).clip(min=0) * (y1 - y0).clip(min=0)
    while order:
        i = order.pop(0)
        keep.append(i)
        if not order:
            break
        rest = np.array(order)
        ix0 = np.maximum(x0[i], x0[rest])
        iy0 = np.maximum(y0[i], y0[rest])
        ix1 = np.minimum(x1[i], x1[rest])
        iy1 = np.minimum(y1[i], y1[rest])
        iw = (ix1 - ix0).clip(min=0)
        ih = (iy1 - iy0).clip(min=0)
        inter = iw * ih
        union = areas[i] + areas[rest] - inter + 1e-6
        iou = inter / union
        order = rest[iou < iou_th].tolist()
    return keep

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
    # Preference order: current YOLO26 ONNX, then legacy YOLOv8 (CoreML, ONNX).
    for candidate in (
        models_dir / "yolo26n.onnx",
        models_dir / "yolov8n.mlpackage",
        models_dir / "yolov8n.onnx",
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
            import coremltools as ct
            _MODEL = ct.models.MLModel(str(mp))
            _IS_COREML = True
        else:
            import onnxruntime as ort
            _MODEL = ort.InferenceSession(str(mp), providers=["CPUExecutionProvider"])
            _IS_COREML = False

        labels_file = mp.parent / "yolov8n_labels.txt"
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
            # The CoreML export bakes NMS into the graph (Ultralytics
            # `export(format="coreml", nms=True)`), so we pass the iou/conf
            # thresholds as model inputs and skip Python-side NMS entirely —
            # `coordinates`/`confidence` are already the final, deduped boxes.
            canvas = np.zeros((_IN_SIZE, _IN_SIZE, 3), dtype=np.float32)
            canvas[:nh, :nw] = np.asarray(im, dtype=np.float32) / 255.0
            canvas_uint8 = (canvas * 255).astype(np.uint8)
            pil_canvas = Image.fromarray(canvas_uint8)

            out = model.predict({
                "image": pil_canvas,
                "iouThreshold": _IOU_TH,
                "confidenceThreshold": _CONF_TH
            })
            conf = np.asarray(out["confidence"])
            coords = np.asarray(out["coordinates"])

            dets = []
            for i in range(len(coords)):
                cx, cy, bw, bh = coords[i]
                cx, cy, bw, bh = cx * _IN_SIZE, cy * _IN_SIZE, bw * _IN_SIZE, bh * _IN_SIZE
                x0, y0, x1, y1 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2

                c_scores = conf[i]
                class_id = c_scores.argmax()
                score = c_scores[class_id]

                dets.append({
                    "class": labels[int(class_id)] if int(class_id) < len(labels) else str(int(class_id)),
                    "conf": float(score),
                    "bbox": [int(x0 / scale), int(y0 / scale), int(x1 / scale), int(y1 / scale)],
                })
            dets.sort(key=lambda d: -d["conf"])
            primary = dets[0]["class"] if dets else None
            return {"detections": dets[:10], "primary": primary}

        else:
            canvas = np.zeros((_IN_SIZE, _IN_SIZE, 3), dtype=np.float32)
            canvas[:nh, :nw] = np.asarray(im, dtype=np.float32) / 255.0
            x = canvas.transpose(2, 0, 1)[None, ...].astype(np.float32)
            out = model.run(None, {model.get_inputs()[0].name: x})[0]
            pred = np.asarray(out)[0]

            # YOLO26 NMS-free export emits [N, 6] = xyxy + score + class_id —
            # already decoded and deduped, so no NMS and no argmax needed.
            if pred.ndim == 2 and pred.shape[1] == 6:
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

            # YOLOv8 raw output: [1, 84, 8400] — 4 box + 80 class scores → NMS.
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
            if boxes.shape[0] == 0:
                return {"detections": [], "primary": None}
            # Convert cxcywh → xyxy in input-image coords first.
            cx, cy, bw, bh = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
            xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
            # Per-class NMS so two different classes overlapping each other survive.
            keep_idx: list[int] = []
            for c in np.unique(cls_ids):
                mask = cls_ids == c
                sub_idx = np.where(mask)[0]
                kept = _nms(xyxy[sub_idx], cls_conf[sub_idx])
                keep_idx.extend(sub_idx[k] for k in kept)
            keep_idx.sort(key=lambda i: -cls_conf[i])
            dets = []
            for i in keep_idx[:20]:
                x0, y0, x1, y1 = xyxy[i].tolist()
                dets.append({
                    "class": labels[int(cls_ids[i])] if int(cls_ids[i]) < len(labels) else str(int(cls_ids[i])),
                    "conf": float(cls_conf[i]),
                    "bbox": [int(x0 / scale), int(y0 / scale), int(x1 / scale), int(y1 / scale)],
                })
            primary = dets[0]["class"] if dets else None
            return {"detections": dets[:10], "primary": primary}
    except Exception:
        return {}
