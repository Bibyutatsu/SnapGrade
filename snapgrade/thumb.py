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


def cleanup_orphans(conn: sqlite3.Connection, dry_run: bool = False) -> list[tuple[Path, int]]:
    """Delete all cached thumbnails whose content hashes are no longer in the DB.

    Returns the list of (deleted_path, size_bytes) tuples.
    """
    import sqlite3

    valid_hashes = set()
    cursor = conn.execute("SELECT DISTINCT content_hash FROM images WHERE content_hash IS NOT NULL")
    for row in cursor:
        valid_hashes.add(row[0])

    deleted = []
    if not CACHE_ROOT.exists():
        return deleted

    for bucket_dir in CACHE_ROOT.iterdir():
        if not bucket_dir.is_dir():
            continue
        for file in bucket_dir.iterdir():
            if not file.is_file() or not file.name.endswith(".jpg"):
                continue
            # File name is {content_hash}_{long_edge}.jpg
            # Get the content_hash by splitting on the last '_'
            parts = file.name.rsplit("_", 1)
            if not parts:
                continue
            content_hash = parts[0]
            if content_hash not in valid_hashes:
                try:
                    size = file.stat().st_size
                except Exception:
                    size = 0
                deleted.append((file, size))
                if not dry_run:
                    try:
                        file.unlink()
                    except Exception:
                        pass
        # Clean up empty bucket directories
        if not dry_run:
            try:
                # Check if bucket_dir is now empty
                if not any(bucket_dir.iterdir()):
                    bucket_dir.rmdir()
            except Exception:
                pass

    return deleted

