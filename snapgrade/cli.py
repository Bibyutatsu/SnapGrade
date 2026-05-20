"""CLI entrypoint."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import db, events, group, models, organize, pipeline, report, xmp

app = typer.Typer(help="SnapGrade — local photo triage and organizer.")
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
    db_path: Path = typer.Option(None, "--db", help="SQLite DB path (default ~/.snapgrade/library.db)"),
    force: bool = typer.Option(False, "--force", help="Re-analyze even if cached"),
    max_edge: int = typer.Option(2000, "--max-edge", help="Long-edge size for analysis"),
    workers: int = typer.Option(0, "--workers", help="Thread count (0 = auto)"),
    models: str = typer.Option("", "--models", help="Comma-separated optional models: scene,screendoc,objects,subject_seg"),
) -> None:
    """Recursively analyze a folder of images."""
    model_list = [m.strip() for m in models.split(",") if m.strip()] or None
    rows: list[dict] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("analyzing…", total=None)
        w = workers if workers > 0 else None
        for result in pipeline.analyze_folder(folder, db_path=db_path, force=force, max_edge=max_edge, workers=w, models=model_list):
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
    library_id: int | None = typer.Option(None, "--library-id", help="Restrict clustering to one library (folder)"),
) -> None:
    """Cluster bursts and pick the best frame per burst."""
    conn = db.connect(db_path) if db_path else db.connect()
    cfg = group.BurstConfig(hamming_threshold=hamming, time_window_seconds=seconds)
    bursts = group.group_bursts(conn, cfg, library_id=library_id)
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
        help="Organize token per level (repeat). Use `snapgrade tokens` to list.",
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
    written = organize.apply_plan(plan, mode=mode, dry_run=not apply, conn=conn)
    verb = "Would write" if not apply else f"Wrote ({mode})"
    console.print(f"{verb} [bold]{written}[/] entries.")


@app.command("events")
def events_cmd(
    gap_hours: float = typer.Option(6.0, "--gap-hours"),
    db_path: Path = typer.Option(None, "--db"),
) -> None:
    """Cluster images into events by capture-time gaps."""
    conn = db.connect(db_path) if db_path else db.connect()
    n = events.build(conn, gap_hours=gap_hours)
    console.print(f"Built [bold]{n}[/] events.")


@app.command("faces")
def faces_cmd(
    detect: bool = typer.Option(True, "--detect/--no-detect"),
    cluster: bool = typer.Option(True, "--cluster/--no-cluster"),
    threshold: float = typer.Option(0.45, "--threshold"),
    db_path: Path = typer.Option(None, "--db"),
) -> None:
    """Detect faces (InsightFace) and greedy-cluster them across the library."""
    from . import face_cluster

    conn = db.connect(db_path) if db_path else db.connect()
    cfg = face_cluster.FaceClusterConfig(similarity_threshold=threshold)
    if detect:
        n = face_cluster.detect_and_store(conn, cfg)
        console.print(f"Detected and stored [bold]{n}[/] new face embeddings.")
    if cluster:
        k = face_cluster.cluster(conn, cfg)
        console.print(f"Formed [bold]{k}[/] face clusters.")


@app.command("report")
def report_cmd(
    out: Path = typer.Argument(..., help="Output HTML path"),
    verdict: str = typer.Option("keeper", "--verdict", help="Filter (keeper/review/reject/all)"),
    db_path: Path = typer.Option(None, "--db"),
) -> None:
    """Render a contact-sheet HTML report."""
    conn = db.connect(db_path) if db_path else db.connect()
    v = None if verdict == "all" else verdict
    n = report.render(conn, out, verdict=v)
    console.print(f"Wrote [bold]{n}[/] cards → {out}")


@app.command("setup")
def setup_cmd(
    only: str = typer.Option(
        "", "--only", help="Comma-separated subset of optional models (default: all)"
    ),
    force: bool = typer.Option(False, "--force", help="Re-download even if present"),
) -> None:
    """Download the optional model weights from the community model host.

    YuNet + FaceLandmarker are fetched automatically on first analyze, so this
    only pulls the opt-in models (U²-Netp, YOLOv8n, NIMA, Places365, screendoc).
    Run once on a fresh machine; weights land in ~/.snapgrade/models/.
    """
    wanted = [m.strip() for m in only.split(",") if m.strip()] or list(models.OPTIONAL_MODELS)
    unknown = [m for m in wanted if m not in models.OPTIONAL_MODELS and m != "places365_labels"]
    if unknown:
        console.print(f"[red]Unknown model(s):[/] {', '.join(unknown)}")
        console.print(f"Choose from: {', '.join(models.OPTIONAL_MODELS)}")
        raise typer.Exit(1)

    console.print(f"Model cache: [dim]{models.MODELS_DIR}[/]")
    ok, skipped, failed = 0, 0, 0
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=console) as prog:
        for name in wanted:
            if not force and models.is_present(name):
                console.print(f"  [green]✓[/] {name} [dim](already present)[/]")
                skipped += 1
                continue
            task = prog.add_task(f"downloading {name}…", total=None)
            try:
                path = models.ensure(name)
                prog.remove_task(task)
                console.print(f"  [green]✓[/] {name} → [dim]{path}[/]")
                ok += 1
            except Exception as e:
                prog.remove_task(task)
                console.print(f"  [red]✗[/] {name}: {e}")
                failed += 1
    console.print(f"\nDone: [green]{ok} downloaded[/], {skipped} present, [red]{failed} failed[/].")
    if failed:
        raise typer.Exit(1)


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Run the FastAPI backend + UI."""
    import uvicorn

    uvicorn.run("snapgrade.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
