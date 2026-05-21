"""Image decoding across JPEG / HEIC / RAW.

Returns 8-bit RGB numpy arrays at a bounded analysis size (default 2000 px long
edge) — full-res isn't needed for any of the metrics, and downscaling keeps
memory bounded on the 8 GB Air.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

RAW_EXTS = {
    ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".raf", ".rw2", ".orf", ".pef", ".dng", ".rwl", ".3fr", ".iiq",
}
JPEG_EXTS = {".jpg", ".jpeg", ".jpe"}
HEIC_EXTS = {".heic", ".heif"}
OTHER_EXTS = {".png", ".tif", ".tiff", ".webp", ".bmp"}

SUPPORTED_EXTS = RAW_EXTS | JPEG_EXTS | HEIC_EXTS | OTHER_EXTS


@dataclass(frozen=True)
class DecodedImage:
    rgb: np.ndarray  # H x W x 3, uint8
    source_w: int
    source_h: int
    kind: str  # "raw" | "jpeg" | "heic" | "other"


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in RAW_EXTS:
        return "raw"
    if ext in JPEG_EXTS:
        return "jpeg"
    if ext in HEIC_EXTS:
        return "heic"
    if ext in OTHER_EXTS:
        return "other"
    return "unknown"


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS


def _fit_long_edge(arr: np.ndarray, max_edge: int) -> np.ndarray:
    h, w = arr.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_edge:
        return arr
    scale = max_edge / long_edge
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    img = Image.fromarray(arr)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    return np.asarray(img)


def _decode_pillow(path: Path, max_edge: int) -> tuple[np.ndarray, int, int]:
    with Image.open(path) as im:
        # libjpeg-turbo supports scaled DCT decode at 1/2, 1/4, 1/8 of native
        # resolution. PIL's `draft` mode taps that path — much cheaper than
        # decoding full-res then resizing. For a 6000-px JPEG with max_edge
        # 2000 we get a ~3000-px decode for free, then a small LANCZOS resize.
        # No-op for non-JPEGs (PIL silently ignores draft for HEIC/PNG/etc.)
        # so the call is safe on every format.
        src_w, src_h = im.size
        if max(src_w, src_h) > max_edge * 2:
            try:
                im.draft("RGB", (max_edge, max_edge))
            except (AttributeError, ValueError):
                pass
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        arr = np.asarray(im)
    return _fit_long_edge(arr, max_edge), src_w, src_h


def _decode_raw(path: Path, max_edge: int) -> tuple[np.ndarray, int, int]:
    # Prefer the embedded JPEG thumbnail when it's large enough — it's already
    # demosaiced by the camera and avoids the multi-hundred-millisecond libraw
    # demosaic cost.
    import rawpy

    with rawpy.imread(str(path)) as raw:
        try:
            thumb = raw.extract_thumb()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            thumb = None

        if thumb is not None and thumb.format == rawpy.ThumbFormat.JPEG:
            from io import BytesIO

            with Image.open(BytesIO(thumb.data)) as im:
                im = ImageOps.exif_transpose(im)
                src_w, src_h = im.size
                im = im.convert("RGB")
                arr = np.asarray(im)
            if max(src_w, src_h) >= max_edge:
                return _fit_long_edge(arr, max_edge), src_w, src_h
            # thumbnail too small — fall through to full demosaic
        rgb = raw.postprocess(
            use_camera_wb=True,
            half_size=True,  # halves linear demosaic cost; plenty of detail for metrics
            no_auto_bright=False,
            output_bps=8,
        )
        src_h, src_w = rgb.shape[:2]
        return _fit_long_edge(rgb, max_edge), src_w * 2, src_h * 2


def decode(path: Path, max_edge: int = 2000) -> DecodedImage:
    """Decode any supported image to an 8-bit RGB array bounded by max_edge."""
    kind = kind_of(path)
    if kind == "unknown":
        raise ValueError(f"Unsupported file type: {path.suffix}")

    if kind == "raw":
        rgb, sw, sh = _decode_raw(path, max_edge)
    else:
        rgb, sw, sh = _decode_pillow(path, max_edge)

    return DecodedImage(rgb=rgb, source_w=sw, source_h=sh, kind=kind)
