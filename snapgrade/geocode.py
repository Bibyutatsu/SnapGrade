"""Offline GPS → country/city lookup.

Uses the `reverse_geocoder` package (ships a ~50 MB SQLite of GeoNames cities).
If the dep isn't installed, falls back to a coarse hemisphere classifier so
the tokens still produce something deterministic instead of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass

_RG = None
_LOADED = False


def _rg():
    global _RG, _LOADED
    if _LOADED:
        return _RG
    _LOADED = True
    try:
        import reverse_geocoder as rg

        _RG = rg
    except Exception:
        _RG = None
    return _RG


@dataclass(frozen=True)
class Place:
    country: str | None
    region: str | None
    city: str | None


def lookup(lat: float | None, lon: float | None) -> Place:
    if lat is None or lon is None:
        return Place(None, None, None)
    rg = _rg()
    if rg is None:
        # Quadrant fallback so tokens still partition predictably.
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        return Place(country=f"hemisphere-{ns}{ew}", region=None, city=None)
    try:
        result = rg.search((lat, lon), mode=1)[0]
        return Place(
            country=result.get("cc"),
            region=result.get("admin1"),
            city=result.get("name"),
        )
    except Exception:
        return Place(None, None, None)
