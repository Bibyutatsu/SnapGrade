"""CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import db, group, organize, pipeline, xmp

app = typer.Typer(help="BlurDetector — local photo triage and organizer.")
console = Console()

_VERDICT_STYLE = {"keeper": "green", "review": "yellow", "reject": "red"}


def _verdict_table(rows: list[dict]) -> Table:
    t = Table(show_header=True, header_style="bold")
    t.add_column("File")
    t.add_column("Verdict")
    t.add_column("Stars", justify="right")
    t.add_column("Reasons")
    for r in rows:
        style = _VERDICT_STYLE.get(r["verdict"], "")
        t.add_row(
            Path(r["path"]).name,
            f"[{style}]{r['verdict']}[/]",
            str(r["stars"]),
            ", ".join(r["reasons"]) if r["reasons"] else "—",
        )
    return t


@app.command()
def analyze(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    db_path: Path = typer.Option(None, "--db", help="SQLite DB path (default ~/.blurdetector/library.db)"),
    force: bool = typer.Option(False, "--force", help="Re-analyze even if cached"),
    max_edge: int = typer.Option(2000, "--max-edge", help="Long-edge size for analysis"),
) -> None:
    """Recursively analyze a folder of images."""
    rows: list[dict] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("analyzing…", total=None)
        for result in pipeline.analyze_folder(folder, db_path=db_path, force=force, max_edge=max_edge):
            progress.update(task, description=f"analyzed {result.path.name}")
            rows.append(
                {
                    "path": str(result.path),
                    "verdict": result.verdict.verdict,
                    "stars": result.verdict.stars,
                    "reasons": result.verdict.reasons,
                }
            )
    console.print(_verdict_table(rows))
    console.print(f"\nAnalyzed [bold]{len(rows)}[/] images.")


@app.command()
def show(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    db_path: Path = typer.Option(None, "--db"),
) -> None:
    """Print cached verdicts for files under [folder] (no re-analysis)."""
    conn = db.connect(db_path) if db_path else db.connect()
    paths = [str(p) for p in pipeline.walk_images(folder)]
    rows = db.fetch_verdicts(conn, paths)
    console.print(_verdict_table(rows))


@app.command("write-xmp")
def write_xmp(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, resolve_path=True),
    db_path: Path = typer.Option(None, "--db"),
) -> None:
    """Emit XMP sidecars (rating + label + reasons) next to each image."""
    conn = db.connect(db_path) if db_path else db.connect()
    paths = [str(p) for p in pipeline.walk_images(folder)]
    rows = db.fetch_verdicts(conn, paths)
    written = 0
    for r in rows:
        xmp.write_sidecar(
            Path(r["path"]),
            rating=r["stars"],
            label=r["label"],
            verdict=r["verdict"],
            reasons=r["reasons"],
        )
        written += 1
    console.print(f"Wrote [bold]{written}[/] XMP sidecars.")


@app.command("group")
def group_cmd(
    db_path: Path = typer.Option(None, "--db"),
    hamming: int = typer.Option(10, "--hamming", help="Max phash hamming distance to merge"),
    seconds: int = typer.Option(3, "--seconds", help="Max capture-time gap within a burst"),
) -> None:
    """Cluster bursts and pick the best frame per burst."""
    conn = db.connect(db_path) if db_path else db.connect()
    cfg = group.BurstConfig(hamming_threshold=hamming, time_window_seconds=seconds)
    bursts = group.group_bursts(conn, cfg)
    console.print(f"Found [bold]{len(bursts)}[/] bursts.")
    for b in bursts:
        console.print(f"  burst #{b.burst_id}: {len(b.image_ids)} frames, best = image #{b.best_image_id}")


@app.command("tokens")
def tokens_cmd() -> None:
    """List available organizer tokens."""
    for name in organize.list_tokens():
        console.print(f"  {name}")


@app.command("organize")
def organize_cmd(
    root: Path = typer.Argument(..., help="Destination root for the organized tree"),
    levels: list[str] = typer.Option(
        ...,
        "--level",
        "-l",
        help="Organize token per level (repeat). Use `blurdetector tokens` to list.",
    ),
    db_path: Path = typer.Option(None, "--db"),
    mode: str = typer.Option("symlink", "--mode", help="symlink | hardlink | copy | move"),
    apply: bool = typer.Option(False, "--apply", help="Actually perform the operation (default is dry-run)"),
    scope: Path = typer.Option(None, "--scope", help="Restrict to images under this folder"),
) -> None:
    """Build (and optionally apply) a hierarchical organizer plan."""
    conn = db.connect(db_path) if db_path else db.connect()
    paths = [str(p) for p in pipeline.walk_images(scope)] if scope else None
    plan = organize.build_plan(conn, root, levels, paths)
    console.print(f"[bold]Plan:[/] {plan.summary()}")
    for entry in plan.entries[:20]:
        console.print(f"  {entry.source.name} → {entry.target}")
    if len(plan.entries) > 20:
        console.print(f"  … and {len(plan.entries) - 20} more")
    written = organize.apply_plan(plan, mode=mode, dry_run=not apply)
    verb = "Would write" if not apply else f"Wrote ({mode})"
    console.print(f"{verb} [bold]{written}[/] entries.")


if __name__ == "__main__":
    app()
