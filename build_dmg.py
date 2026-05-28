"""Build a distributable DMG for SnapGrade.app.

Usage:
    uv run python build_dmg.py
    uv run python build_dmg.py --version 0.1.4

Produces: dist/SnapGrade-<version>.dmg
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "SnapGrade"
DEFAULT_VERSION = "0.2.0"


def run(cmd: list, **kw):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        print(f"Error: command failed (exit {result.returncode})")
        sys.exit(result.returncode)
    return result


def build_dmg(version: str):
    workspace = Path(__file__).parent.resolve()
    app_src = workspace / f"dist/{APP_NAME}.app"
    dmg_out = workspace / f"dist/{APP_NAME}-{version}.dmg"
    tmp_dmg = workspace / f"dist/{APP_NAME}-{version}-tmp.dmg"

    if not app_src.exists():
        print(f"Error: {app_src} not found — run build_app.py first.")
        sys.exit(1)

    # Clean old DMG
    dmg_out.unlink(missing_ok=True)
    tmp_dmg.unlink(missing_ok=True)

    print(f"Building {dmg_out.name} …")

    # ── Stage into a temp folder ──────────────────────────────────────────────
    with tempfile.TemporaryDirectory(prefix="snapgrade_dmg_") as staging_str:
        staging = Path(staging_str)

        # Copy app
        print("  Copying .app …")
        shutil.copytree(app_src, staging / f"{APP_NAME}.app", symlinks=True)

        # Symlink to /Applications for drag-install UX
        (staging / "Applications").symlink_to("/Applications")

        # ── Create writeable DMG from staging ─────────────────────────────────
        run([
            "hdiutil", "create",
            "-volname", APP_NAME,
            "-srcfolder", str(staging),
            "-ov",           # overwrite existing
            "-format", "UDRW",   # writeable so we can set background/icon pos
            str(tmp_dmg),
        ])

    # ── Convert to compressed read-only DMG ───────────────────────────────────
    run([
        "hdiutil", "convert",
        str(tmp_dmg),
        "-format", "UDZO",
        "-imagekey", "zlib-level=9",
        "-o", str(dmg_out),
    ])
    tmp_dmg.unlink(missing_ok=True)

    size_mb = dmg_out.stat().st_size / 1_000_000
    print(f"\n✓ {dmg_out.name}  ({size_mb:.0f} MB)")
    print(f"  Path: {dmg_out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--version", default=DEFAULT_VERSION)
    args = p.parse_args()
    build_dmg(args.version)
