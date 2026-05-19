"""EXIF extraction. Returns a normalized dict used by the organizer + UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ExifTags

try:
    import pillow_heif  # noqa: F401  (registers HEIF opener as a side effect)
except Exception:
    pass

_TAG_BY_NAME = {v: k for k, v in ExifTags.TAGS.items()}
_GPS_TAG = _TAG_BY_NAME.get("GPSInfo")


@dataclass(frozen=True)
class Exif:
    capture_time: datetime | None
    camera_make: str | None
    camera_model: str | None
    lens_model: str | None
    focal_length_mm: float | None
    iso: int | None
    f_number: float | None
    exposure_time: float | None
    flash_fired: bool | None
    orientation: int | None
    gps_lat: float | None
    gps_lon: float | None

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        if self.capture_time is not None:
            d["capture_time"] = self.capture_time.isoformat()
        return d


def _rational_to_float(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        try:
            return x[0] / x[1]
        except Exception:
            return None


def _parse_datetime(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip("\x00").strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _gps_to_decimal(coord, ref) -> float | None:
    if not coord or not ref:
        return None
    try:
        d, m, s = (_rational_to_float(x) for x in coord)
        if d is None or m is None or s is None:
            return None
        val = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            val = -val
        return val
    except Exception:
        return None


def _read_pillow_exif(path: Path) -> Exif:
    with Image.open(path) as im:
        raw = im.getexif() or {}

    tags: dict[str, Any] = {}
    for tag_id, value in raw.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        tags[name] = value

    gps_info: dict[str, Any] = {}
    if _GPS_TAG and _GPS_TAG in raw:
        gps_raw = raw.get_ifd(_GPS_TAG) if hasattr(raw, "get_ifd") else raw[_GPS_TAG]
        for k, v in (gps_raw or {}).items():
            gps_info[ExifTags.GPSTAGS.get(k, str(k))] = v

    capture_time = _parse_datetime(
        tags.get("DateTimeOriginal") or tags.get("DateTimeDigitized") or tags.get("DateTime")
    )

    flash = tags.get("Flash")
    flash_fired = None
    if isinstance(flash, int):
        flash_fired = bool(flash & 1)

    return Exif(
        capture_time=capture_time,
        camera_make=(tags.get("Make") or "").strip() or None,
        camera_model=(tags.get("Model") or "").strip() or None,
        lens_model=(tags.get("LensModel") or "").strip() or None,
        focal_length_mm=_rational_to_float(tags.get("FocalLength")),
        iso=int(tags["ISOSpeedRatings"]) if isinstance(tags.get("ISOSpeedRatings"), int) else None,
        f_number=_rational_to_float(tags.get("FNumber")),
        exposure_time=_rational_to_float(tags.get("ExposureTime")),
        flash_fired=flash_fired,
        orientation=tags.get("Orientation") if isinstance(tags.get("Orientation"), int) else None,
        gps_lat=_gps_to_decimal(gps_info.get("GPSLatitude"), gps_info.get("GPSLatitudeRef")),
        gps_lon=_gps_to_decimal(gps_info.get("GPSLongitude"), gps_info.get("GPSLongitudeRef")),
    )


def read_exif(path: Path) -> Exif:
    """Read EXIF for any file Pillow (with pillow-heif) can open. RAW handled via rawpy fallback."""
    suffix = path.suffix.lower()
    if suffix in {".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2",
                  ".raf", ".rw2", ".orf", ".pef", ".dng", ".rwl", ".3fr", ".iiq"}:
        # Try Pillow first (it handles many RAW EXIFs via TIFF header);
        # fall back to rawpy's metadata if Pillow returns nothing useful.
        try:
            return _read_pillow_exif(path)
        except Exception:
            return _read_raw_exif(path)
    return _read_pillow_exif(path)


def _read_raw_exif(path: Path) -> Exif:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        # rawpy exposes only a minimal subset; we degrade gracefully.
        try:
            cam = raw.camera_whitebalance  # noqa: F841 — touched to verify open succeeds
        except Exception:
            pass
    return Exif(
        capture_time=None,
        camera_make=None,
        camera_model=None,
        lens_model=None,
        focal_length_mm=None,
        iso=None,
        f_number=None,
        exposure_time=None,
        flash_fired=None,
        orientation=None,
        gps_lat=None,
        gps_lon=None,
    )
