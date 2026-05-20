"""On-demand thumbnail cache.

Thumbnails are keyed by content hash so renames/moves don't invalidate them,
and they're written as JPEG quality-85 (visually transparent, ~1/20 the size
of the analysis image).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from . import decode

CACHE_ROOT = Path.home() / ".snapgrade" / "thumbs"


def _cache_path(content_hash: str, long_edge: int) -> Path:
    bucket = content_hash[:2]
    return CACHE_ROOT / bucket / f"{content_hash}_{long_edge}.jpg"


def get_or_build(source: Path, content_hash: str, long_edge: int = 512) -> Path:
    out = _cache_path(content_hash, long_edge)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    img = decode.decode(source, max_edge=long_edge)
    Image.fromarray(img.rgb).save(out, format="JPEG", quality=85, optimize=True)
    return out


def render_to_bytes(source: Path, long_edge: int = 1600) -> bytes:
    img = decode.decode(source, max_edge=long_edge)
    buf = BytesIO()
    Image.fromarray(img.rgb).save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()
