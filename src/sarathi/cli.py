from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from . import builder, exporter, scanner, watcher

console = Console()

DEFAULT_MODEL = "llama3.2-vision"


@click.group()
def cli():
    """Sarathi — turns your project results into gorgeous presentations."""


@cli.command()
@click.argument("name")
@click.argument("description")
@click.option("--model", default=DEFAULT_MODEL, show_default=True,
              help="Ollama model to use for generation.")
def init(name: str, description: str, model: str):
    """Scaffold a new project folder.

    \b
    NAME         Project folder name (created in current directory)
    DESCRIPTION  What this project is about (used as LLM context)
    """
    project_dir = Path(name)
    if project_dir.exists():
        console.print(f"[red]Folder '{name}' already exists.[/red]")
        raise SystemExit(1)

    for sub in ("data", "plots", "notes", "output"):
        (project_dir / sub).mkdir(parents=True)

    meta = {
        "name": name,
        "description": description,
        "created": datetime.now().isoformat(timespec="seconds"),
        "model": model,
    }
    (project_dir / "project.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )

    console.print(Panel(
        f"[bold green]Project '{name}' created![/bold green]\n\n"
        f"Drop your results into:\n"
        f"  [cyan]{name}/data/[/cyan]   — CSV, JSON\n"
        f"  [cyan]{name}/plots/[/cyan]  — PNG, SVG images\n"
        f"  [cyan]{name}/notes/[/cyan]  — text, markdown\n\n"
        f"Then run:\n"
        f"  [bold]sarathi make {name}/[/bold]",
        title="sarathi init",
    ))


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--once", is_flag=True, help="Generate once and exit (no watching).")
@click.option("--model", default=None,
              help="Override the Ollama model from project.json.")
def make(folder: str, once: bool, model: str | None):
    """Generate a presentation from FOLDER's results.

    Watches for changes by default; use --once for a single run.
    """
    project_dir = Path(folder).resolve()
    meta_path = project_dir / "project.json"

    if not meta_path.exists():
        console.print(
            f"[red]No project.json found in {project_dir}.[/red]\n"
            "Run [bold]sarathi init[/bold] first."
        )
        raise SystemExit(1)

    meta = json.loads(meta_path.read_text())
    effective_model = model or meta.get("model", DEFAULT_MODEL)
    output_dir = project_dir / "output"
    output_dir.mkdir(exist_ok=True)

    def generate():
        console.print(f"[dim][sarathi][/dim] Scanning {project_dir.name}...")
        files = scanner.scan(project_dir)

        if not files:
            console.print("[yellow][sarathi] No result files found yet — waiting.[/yellow]")
            return

        console.print(
            f"[dim][sarathi][/dim] Found {len(files)} file(s) — "
            f"calling {effective_model}..."
        )

        html_out = output_dir / "presentation.html"
        pdf_out = output_dir / "presentation.pdf"

        try:
            builder.generate(
                project_name=meta["name"],
                description=meta["description"],
                files=files,
                model=effective_model,
                output_html=html_out,
            )
            console.print(f"[green][sarathi] HTML → {html_out}[/green]")
        except Exception as exc:
            console.print(f"[red][sarathi] LLM error: {exc}[/red]")
            return

        try:
            exporter.to_pdf(html_out, pdf_out)
            console.print(f"[green][sarathi] PDF  → {pdf_out}[/green]")
        except Exception as exc:
            console.print(f"[yellow][sarathi] PDF export failed: {exc}[/yellow]")

    generate()

    if once:
        return

    console.print(
        f"\n[dim][sarathi] Watching {project_dir.name}/ for changes "
        "(Ctrl+C to stop)...[/dim]"
    )
    watcher.watch(project_dir, generate)
