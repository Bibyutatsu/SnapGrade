"""Organize apply + undo round-trip."""

from __future__ import annotations

from pathlib import Path

from snapgrade import db, organize


def _seed(conn, src_dir: Path, n: int = 3) -> None:
    lib = db.ensure_library(conn, str(src_dir))
    for i in range(n):
        p = src_dir / f"img_{i}.jpg"
        p.write_bytes(b"x")
        img_id = db.upsert_image(conn, {"path": str(p), "size_bytes": 1, "mtime": 1.0, "library_id": lib})
        db.save_metrics(conn, img_id, {"kind": "jpeg"})
        db.save_verdict(conn, img_id, "keeper", 5, "green", [])


def test_symlink_undo_removes_links(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    _seed(conn, src)

    plan = organize.build_plan(conn, out, ["quality:verdict"])
    written = organize.apply_plan(plan, mode="symlink", dry_run=False, conn=conn)
    assert written == 3
    links = list(out.rglob("*.jpg"))
    assert len(links) == 3 and all(p.is_symlink() for p in links)

    result = organize.undo_last(conn)
    assert result["undone"] == 3
    assert list(out.rglob("*.jpg")) == []
    # Sources untouched.
    assert len(list(src.glob("*.jpg"))) == 3


def test_move_undo_restores_paths(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "out"
    _seed(conn, src, n=2)

    plan = organize.build_plan(conn, out, ["quality:verdict"])
    organize.apply_plan(plan, mode="move", dry_run=False, conn=conn)
    assert len(list(out.rglob("*.jpg"))) == 2
    assert list(src.glob("*.jpg")) == []  # moved away

    result = organize.undo_last(conn)
    assert result["undone"] == 2
    assert len(list(src.glob("*.jpg"))) == 2  # moved back
    # DB paths restored to the src dir.
    paths = [r[0] for r in conn.execute("SELECT path FROM images").fetchall()]
    assert all(str(src) in p for p in paths)


def test_undo_with_no_runs_is_noop(tmp_path, monkeypatch):
    from snapgrade import db as db_mod
    dbp = tmp_path / "t.db"
    monkeypatch.setattr(db_mod, "DEFAULT_DB", dbp)
    conn = db.connect(dbp)
    assert organize.undo_last(conn) == {"undone": 0, "skipped": 0}
