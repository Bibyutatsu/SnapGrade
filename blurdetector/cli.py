"""CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import db, pipeline, xmp

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


if __name__ == "__main__":
    app()
