"""Shared pytest fixtures for the SnapGrade test suite.

Fixtures here let individual smoke / bench files share the same Images/ root
and avoid re-initialising the pipeline per test module.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def images_root() -> Path:
    """Root of the labelled smoke corpus.

    Overridable via SNAPGRADE_IMAGES_ROOT so CI / contributors can point at a
    different tree without editing tests.
    """
    return Path(os.environ.get("SNAPGRADE_IMAGES_ROOT", "/Users/oindrila/Projects/BlurDetector/Images"))


@pytest.fixture(scope="session")
def bucket_files(images_root: Path):
    """Return `(bucket_name) -> list[Path]` for every non-empty subfolder."""

    skip_exts = {".ds_store", ".mov", ".psd"}

    def _list(bucket: str) -> list[Path]:
        d = images_root / bucket
        if not d.is_dir():
            return []
        return sorted(
            p for p in d.iterdir()
            if p.is_file() and p.suffix.lower() not in skip_exts and not p.name.startswith(".")
        )

    return _list
