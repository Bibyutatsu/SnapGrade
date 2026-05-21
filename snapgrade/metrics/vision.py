"""Apple Vision framework wrappers (macOS-only, runs on the Neural Engine).

These are thin wrappers over `Vision.framework` via PyObjC. They need no model
downloads — the detectors ship with macOS — and they degrade gracefully: if
PyObjC / Vision isn't importable (non-macOS, missing extra), every public
function returns an empty/None result instead of raising, matching the
optional-import pattern used for rawpy / insightface / coremltools.

Coordinate convention: Vision returns normalized boxes with the origin at the
*bottom-left*. We convert everything to top-left pixel coordinates
`[x0, y0, x1, y1]` to match the rest of SnapGrade.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def is_available() -> bool:
    """True if the Vision framework can be imported on this machine."""
    try:
        import Vision  # noqa: F401
        import Quartz  # noqa: F401
    except Exception:
        return False
    return True


def _cgimage_from_rgb(rgb: np.ndarray):
    """Build a CGImage from an HxWx3 uint8 RGB array (adds an ignored alpha)."""
    import Quartz

    h, w = rgb.shape[:2]
    # 32bpp RGBA with the alpha byte ignored — the most reliable CGImage layout.
    rgba = np.dstack([rgb, np.full((h, w), 255, dtype=np.uint8)])
    data = rgba.tobytes()
    provider = Quartz.CGDataProviderCreateWithData(None, data, len(data), None)
    colorspace = Quartz.CGColorSpaceCreateDeviceRGB()
    bitmap_info = Quartz.kCGImageAlphaNoneSkipLast | Quartz.kCGBitmapByteOrderDefault
    return Quartz.CGImageCreate(
        w, h, 8, 32, w * 4, colorspace, bitmap_info,
        provider, None, False, Quartz.kCGRenderingIntentDefault,
    )


def _handler(rgb: np.ndarray):
    import Vision

    cg = _cgimage_from_rgb(rgb)
    if cg is None:
        return None
    return Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, {})


def _perform(handler, request) -> bool:
    ok, _err = handler.performRequests_error_([request], None)
    return bool(ok)


def _norm_box_to_px(box, w: int, h: int) -> list[int]:
    """VN normalized bottom-left box → top-left pixel [x0, y0, x1, y1]."""
    x = box.origin.x * w
    bw = box.size.width * w
    bh = box.size.height * h
    # Flip Y: Vision origin is bottom-left.
    y_top = (1.0 - box.origin.y - box.size.height) * h
    return [int(x), int(y_top), int(x + bw), int(y_top + bh)]


def recognize_text(
    rgb: np.ndarray, max_results: int = 50, accurate: bool = False,
) -> list[dict[str, Any]]:
    """OCR. Returns [{text, confidence, bbox}], empty on any failure.

    `accurate=False` (default) uses Vision's "Fast" recognition level: ~3-5×
    faster than Accurate and good enough for screenshot/document detection,
    which is the only consumer in the pipeline. Pass `accurate=True` when the
    text itself matters (future: full-text library search).
    """
    if not is_available():
        return []
    try:
        import Vision

        h, w = rgb.shape[:2]
        handler = _handler(rgb)
        if handler is None:
            return []
        req = Vision.VNRecognizeTextRequest.alloc().init()
        level = (
            Vision.VNRequestTextRecognitionLevelAccurate
            if accurate
            else Vision.VNRequestTextRecognitionLevelFast
        )
        req.setRecognitionLevel_(level)
        # Language correction adds significant latency for no gain in the
        # screenshot/document classifier path.
        try:
            req.setUsesLanguageCorrection_(False)
        except AttributeError:
            pass
        if not _perform(handler, req):
            return []
        out: list[dict[str, Any]] = []
        for obs in (req.results() or [])[:max_results]:
            cands = obs.topCandidates_(1)
            if not cands:
                continue
            top = cands[0]
            out.append({
                "text": str(top.string()),
                "confidence": float(top.confidence()),
                "bbox": _norm_box_to_px(obs.boundingBox(), w, h),
            })
        return out
    except Exception:
        return []


def document_segmentation(rgb: np.ndarray) -> dict[str, Any] | None:
    """Detect a document quad. Returns {confidence, bbox} or None."""
    if not is_available():
        return None
    try:
        import Vision

        h, w = rgb.shape[:2]
        handler = _handler(rgb)
        if handler is None:
            return None
        req = Vision.VNDetectDocumentSegmentationRequest.alloc().init()
        if not _perform(handler, req):
            return None
        results = req.results() or []
        if not results:
            return None
        obs = results[0]
        return {
            "confidence": float(obs.confidence()),
            "bbox": _norm_box_to_px(obs.boundingBox(), w, h),
        }
    except Exception:
        return None


def recognize_animals(rgb: np.ndarray) -> list[dict[str, Any]]:
    """Detect cats/dogs. Returns [{species, confidence, bbox}]."""
    if not is_available():
        return []
    try:
        import Vision

        h, w = rgb.shape[:2]
        handler = _handler(rgb)
        if handler is None:
            return []
        req = Vision.VNRecognizeAnimalsRequest.alloc().init()
        if not _perform(handler, req):
            return []
        out: list[dict[str, Any]] = []
        for obs in req.results() or []:
            for label in obs.labels() or []:
                out.append({
                    "species": str(label.identifier()),
                    "confidence": float(label.confidence()),
                    "bbox": _norm_box_to_px(obs.boundingBox(), w, h),
                })
        return out
    except Exception:
        return []


def attention_saliency(rgb: np.ndarray) -> dict[str, Any] | None:
    """Attention-based saliency. Returns {bbox, confidence} for the strongest
    salient region (Vision returns up to ~3, we take the highest-confidence
    one), or None if unavailable / no salient region found.

    Vision's attention saliency is ANE-accelerated and qualitatively much
    sharper than OpenCV's StaticSaliencyFineGrained — callers should prefer
    this when available and fall back to cv2 only on non-macOS.
    """
    if not is_available():
        return None
    try:
        import Vision

        h, w = rgb.shape[:2]
        handler = _handler(rgb)
        if handler is None:
            return None
        req = Vision.VNGenerateAttentionBasedSaliencyImageRequest.alloc().init()
        if not _perform(handler, req):
            return None
        results = req.results() or []
        if not results:
            return None
        obs = results[0]
        objs = obs.salientObjects() or []
        if not objs:
            return None
        best = max(objs, key=lambda o: float(o.confidence()))
        return {
            "bbox": _norm_box_to_px(best.boundingBox(), w, h),
            "confidence": float(best.confidence()),
        }
    except Exception:
        return None


def horizon_angle(rgb: np.ndarray) -> float | None:
    """Detected horizon tilt in degrees (+ = clockwise), or None."""
    if not is_available():
        return None
    try:
        import Vision

        handler = _handler(rgb)
        if handler is None:
            return None
        req = Vision.VNDetectHorizonRequest.alloc().init()
        if not _perform(handler, req):
            return None
        results = req.results() or []
        if not results:
            return None
        return float(np.degrees(results[0].angle()))
    except Exception:
        return None
