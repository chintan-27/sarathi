from __future__ import annotations

import json
import webbrowser
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import builder, exporter, scanner, watcher
from . import tracker as trk
from . import config as cfg
from . import portfolio as ptf

console = Console()

DEFAULT_MODEL = "claude-code"

VISION_MODEL_KEYWORDS = {"llava", "vision", "vl", "gemma3", "minicpm"}


def _is_vision(name: str) -> bool:
    return any(k in name.lower() for k in VISION_MODEL_KEYWORDS)


def _dual(english: str, sanskrit: str):
    """Decorator factory that registers two Click commands with the same implementation."""
    def decorator(fn):
        fn = click.command(english)(fn)
        # Register Sanskrit alias pointing to the same callback
        alias = click.command(sanskrit)(fn.callback)
        # Copy params
        alias.params = list(fn.params)
        alias.help = fn.help
        return fn, alias
    return decorator


@click.group()
def cli():
    """Sarathi — your personal project companion. Turns raw results into polished presentations."""


# ── helper to register dual-named commands ────────────────────────────────────

def _add(english_cmd, sanskrit_cmd):
    cli.add_command(english_cmd)
    cli.add_command(sanskrit_cmd)


# ── init / arambh ─────────────────────────────────────────────────────────────

def _init_impl(name: str, description: str, model: str):
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
    trk.init_tracker(project_dir)
    trk.log_event(project_dir, "init", name=name)
    ptf.register_project(project_dir)

    console.print(Panel(
        f"[bold green]Project '{name}' created![/bold green]\n\n"
        f"Drop your results into:\n"
        f"  [cyan]{name}/data/[/cyan]   — CSV, JSON\n"
        f"  [cyan]{name}/plots/[/cyan]  — PNG, SVG images\n"
        f"  [cyan]{name}/notes/[/cyan]  — text, markdown\n\n"
        f"Then run:\n"
        f"  [bold]sarathi yatra {name}/[/bold]  (or [bold]sarathi track {name}/[/bold])",
        title="sarathi init / arambh",
    ))


@click.command("init")
@click.argument("name")
@click.argument("description")
@click.option("--model", default=DEFAULT_MODEL, show_default=True,
              help="Ollama model to use for generation.")
def init_cmd(name, description, model):
    """Scaffold a new project folder. (Sanskrit: arambh)"""
    _init_impl(name, description, model)


@click.command("arambh")
@click.argument("name")
@click.argument("description")
@click.option("--model", default=DEFAULT_MODEL, show_default=True,
              help="Ollama model to use for generation.")
def arambh_cmd(name, description, model):
    """Scaffold a new project folder. (arambh = beginning)"""
    _init_impl(name, description, model)


cli.add_command(init_cmd)
cli.add_command(arambh_cmd)


# ── track / yatra ─────────────────────────────────────────────────────────────

def _track_impl(folder: str, once: bool, model: str | None, edit_outline: bool):
    project_dir = Path(folder).resolve()
    meta_path = project_dir / "project.json"

    if not meta_path.exists():
        name = click.prompt("Project name")
        description = click.prompt("Project description")
        meta = {
            "name": name,
            "description": description,
            "created": datetime.now().isoformat(timespec="seconds"),
            "model": model or DEFAULT_MODEL,
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    meta = json.loads(meta_path.read_text())
    trk.init_tracker(project_dir)
    ptf.register_project(project_dir)

    project_cfg = cfg.load_project_config(project_dir)
    effective_model = model or meta.get("model") or project_cfg["model"]
    theme = project_cfg.get("theme", "dark-gradient")
    output_dir = project_dir / "output"
    output_dir.mkdir(exist_ok=True)

    milestones = trk.get_milestones(project_dir)
    last_gen = trk.last_generated(project_dir)
    console.print(
        f"[dim][sarathi][/dim] Tracking [bold]{meta['name']}[/bold] — "
        f"{len(milestones)} milestone(s), last generated: {last_gen or 'never'}"
    )

    outline_path = (project_dir / ".sarathi" / "outline.json") if edit_outline else None

    def generate():
        console.print(f"[dim][sarathi][/dim] Scanning {project_dir.name}...")
        files = scanner.scan(project_dir)

        if not files:
            console.print("[yellow][sarathi] No result files found yet — waiting.[/yellow]")
            return

        trk.log_event(project_dir, "checkpoint",
                      file_hashes=trk.snapshot_hashes(project_dir))
        console.print(
            f"[dim][sarathi][/dim] Found {len(files)} file(s) — calling {effective_model}..."
        )

        html_out = output_dir / "presentation.html"
        pdf_out = output_dir / "presentation.pdf"

        if edit_outline and outline_path and not outline_path.exists():
            console.print(
                f"\n[yellow][sarathi] Pass 1 will save outline to "
                f"[bold].sarathi/outline.json[/bold].\n"
                f"Edit it, then re-run without --edit-outline to render slides.[/yellow]\n"
            )

        try:
            builder.generate(
                project_name=meta["name"],
                description=meta["description"],
                files=files,
                model=effective_model,
                output_html=html_out,
                project_dir=project_dir,
                theme=theme,
                outline_path=outline_path,
            )
            trk.log_event(project_dir, "generated",
                          html=str(html_out.relative_to(project_dir)),
                          model=effective_model)
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


@click.command("track")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--once", is_flag=True, help="Generate once and exit.")
@click.option("--model", default=None, help="Override the Ollama model.")
@click.option("--edit-outline", is_flag=True,
              help="Save JSON outline for editing before rendering slides.")
def track_cmd(folder, once, model, edit_outline):
    """Track a project folder and generate presentations. (Sanskrit: yatra)"""
    _track_impl(folder, once, model, edit_outline)


@click.command("yatra")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--once", is_flag=True, help="Generate once and exit.")
@click.option("--model", default=None, help="Override the Ollama model.")
@click.option("--edit-outline", is_flag=True,
              help="Save JSON outline for editing before rendering slides.")
def yatra_cmd(folder, once, model, edit_outline):
    """Track a project folder and generate presentations. (yatra = journey)"""
    _track_impl(folder, once, model, edit_outline)


cli.add_command(track_cmd)
cli.add_command(yatra_cmd)


# ── make / rachna (legacy one-shot, wraps track --once) ───────────────────────

@click.command("make")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--once", is_flag=True, default=True, hidden=True)
@click.option("--model", default=None, help="Override the Ollama model.")
@click.option("--edit-outline", is_flag=True)
def make_cmd(folder, once, model, edit_outline):
    """Generate a presentation (one-shot). (Sanskrit: rachna)"""
    _track_impl(folder, True, model, edit_outline)


@click.command("rachna")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--model", default=None, help="Override the Ollama model.")
@click.option("--edit-outline", is_flag=True)
def rachna_cmd(folder, model, edit_outline):
    """Generate a presentation (one-shot). (rachna = creation)"""
    _track_impl(folder, True, model, edit_outline)


cli.add_command(make_cmd)
cli.add_command(rachna_cmd)


# ── mark / chinh ──────────────────────────────────────────────────────────────

def _mark_impl(folder: str, name: str):
    project_dir = Path(folder).resolve()
    trk.init_tracker(project_dir)
    hashes = trk.snapshot_hashes(project_dir)
    trk.log_event(project_dir, "milestone", label=name, file_hashes=hashes)
    console.print(f"[green][sarathi] ★ Milestone [bold]\"{name}\"[/bold] marked.[/green]")


@click.command("mark")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--name", required=True, help="Milestone label.")
def mark_cmd(folder, name):
    """Mark a milestone in the project timeline. (Sanskrit: chinh)"""
    _mark_impl(folder, name)


@click.command("chinh")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--name", required=True, help="Milestone label.")
def chinh_cmd(folder, name):
    """Mark a milestone in the project timeline. (chinh = waypoint)"""
    _mark_impl(folder, name)


cli.add_command(mark_cmd)
cli.add_command(chinh_cmd)


# ── log / itihas ──────────────────────────────────────────────────────────────

def _log_impl(folder: str):
    project_dir = Path(folder).resolve()
    events = trk.get_timeline(project_dir)
    if not events:
        console.print("[yellow]No timeline events yet.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Time", style="dim", width=19)
    table.add_column("Event", width=14)
    table.add_column("Details")

    for e in events:
        ts = e.get("ts", "")[:16].replace("T", " ")
        etype = e.get("event", "")
        if etype == "milestone":
            label = f"★ [bold yellow]{e.get('label', '')}[/bold yellow]"
            table.add_row(ts, "[yellow]MILESTONE[/yellow]", label)
        elif etype == "generated":
            table.add_row(ts, "[green]generated[/green]",
                          e.get("html", "") + f"  [{e.get('model', '')}]")
        elif etype == "checkpoint":
            n = len(e.get("file_hashes", {}))
            table.add_row(ts, "[dim]checkpoint[/dim]", f"{n} file(s) snapshotted")
        elif etype == "file_added":
            table.add_row(ts, "file_added", e.get("file", ""))
        else:
            table.add_row(ts, etype, "")

    console.print(table)


@click.command("log")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def log_cmd(folder):
    """Show the project timeline. (Sanskrit: itihas)"""
    _log_impl(folder)


@click.command("itihas")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def itihas_cmd(folder):
    """Show the project timeline. (itihas = chronicle)"""
    _log_impl(folder)


cli.add_command(log_cmd)
cli.add_command(itihas_cmd)


# ── status / sthiti ───────────────────────────────────────────────────────────

def _status_impl(folder: str):
    project_dir = Path(folder).resolve()
    meta_path = project_dir / "project.json"
    if not meta_path.exists():
        console.print("[red]No project.json found. Run sarathi init first.[/red]")
        raise SystemExit(1)

    meta = json.loads(meta_path.read_text())
    project_cfg = cfg.load_project_config(project_dir)
    milestones = trk.get_milestones(project_dir)
    last_gen = trk.last_generated(project_dir)
    pending = trk.files_since_last_generated(project_dir)

    console.print(Panel(
        f"[bold]{meta['name']}[/bold]\n"
        f"[dim]{meta.get('description', '')}[/dim]\n\n"
        f"Model  : [cyan]{meta.get('model', project_cfg['model'])}[/cyan]\n"
        f"Theme  : [cyan]{project_cfg.get('theme', 'dark-gradient')}[/cyan]\n"
        f"Last generated : [green]{last_gen or 'never'}[/green]\n"
        f"Milestones     : [yellow]{len(milestones)}[/yellow]\n"
        f"Changed since last gen : [{'red' if pending else 'green'}]{len(pending)} file(s)[/{'red' if pending else 'green'}]"
        + (("\n  " + "\n  ".join(pending)) if pending else ""),
        title="sarathi status / sthiti",
    ))


@click.command("status")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def status_cmd(folder):
    """Show current project state. (Sanskrit: sthiti)"""
    _status_impl(folder)


@click.command("sthiti")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def sthiti_cmd(folder):
    """Show current project state. (sthiti = current state)"""
    _status_impl(folder)


cli.add_command(status_cmd)
cli.add_command(sthiti_cmd)


# ── open / darshan ────────────────────────────────────────────────────────────

def _open_impl(folder: str):
    project_dir = Path(folder).resolve()
    html = project_dir / "output" / "presentation.html"
    if not html.exists():
        console.print("[red]No presentation.html found. Run sarathi rachna first.[/red]")
        raise SystemExit(1)
    webbrowser.open(html.as_uri())
    console.print(f"[green]Opened {html}[/green]")


@click.command("open")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def open_cmd(folder):
    """Open the latest presentation in a browser. (Sanskrit: darshan)"""
    _open_impl(folder)


@click.command("darshan")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
def darshan_cmd(folder):
    """Open the latest presentation in a browser. (darshan = viewing)"""
    _open_impl(folder)


cli.add_command(open_cmd)
cli.add_command(darshan_cmd)


# ── clean ─────────────────────────────────────────────────────────────────────

@click.command("clean")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def clean_cmd(folder, yes):
    """Wipe output/ and .sarathi/viz/ cache."""
    project_dir = Path(folder).resolve()
    targets = [project_dir / "output", project_dir / ".sarathi" / "viz"]
    if not yes:
        click.confirm(
            f"Delete output/ and .sarathi/viz/ in {project_dir.name}?", abort=True
        )
    import shutil
    for t in targets:
        if t.exists():
            shutil.rmtree(t)
            t.mkdir()
            console.print(f"[dim]Cleared {t.relative_to(project_dir)}[/dim]")
    console.print("[green]Done.[/green]")


cli.add_command(clean_cmd)


# ── models ────────────────────────────────────────────────────────────────────

@click.command("models")
def models_cmd():
    """List available Ollama models, flagging vision-capable ones."""
    import ollama
    try:
        result = ollama.list()
    except Exception as exc:
        console.print(f"[red]Could not connect to Ollama: {exc}[/red]")
        raise SystemExit(1)

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Model")
    table.add_column("Size")
    table.add_column("Capability")

    for m in result.models:
        name = m.model
        size_gb = f"{m.size / 1e9:.1f} GB" if hasattr(m, "size") and m.size else "—"
        cap = "[bold magenta][vision][/bold magenta]" if _is_vision(name) else ""
        table.add_row(name, size_gb, cap)

    console.print(table)
    console.print(
        "\n[dim]Recommended: [bold]kimi-k2.5:cloud[/bold] or [bold]qwen3.5[/bold] "
        "(via Ollama's Anthropic-compatible API) · "
        "[bold]llama3.2-vision:11b[/bold] (local image analysis)\n"
        "Setup: [cyan]ollama launch claude --model kimi-k2.5:cloud[/cyan][/dim]"
    )


cli.add_command(models_cmd)


# ── theme ─────────────────────────────────────────────────────────────────────

THEMES = ["dark-gradient", "dracula", "light", "minimal"]


@click.command("theme")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--set", "theme_name", type=click.Choice(THEMES), required=True,
              help="Theme name.")
def theme_cmd(folder, theme_name):
    """Set the presentation theme for a project."""
    project_dir = Path(folder).resolve()
    trk.init_tracker(project_dir)
    cfg.save_project_config(project_dir, {"theme": theme_name})
    console.print(f"[green]Theme set to [bold]{theme_name}[/bold].[/green]")


cli.add_command(theme_cmd)


# ── export ────────────────────────────────────────────────────────────────────

@click.command("export")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--format", "fmt", type=click.Choice(["html", "pdf", "zip"]),
              default="pdf", show_default=True)
def export_cmd(folder, fmt):
    """Re-export the presentation without re-generating."""
    import shutil
    project_dir = Path(folder).resolve()
    html_src = project_dir / "output" / "presentation.html"
    pdf_src = project_dir / "output" / "presentation.pdf"
    name = json.loads((project_dir / "project.json").read_text())["name"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not html_src.exists():
        console.print("[red]No presentation.html found. Run sarathi rachna first.[/red]")
        raise SystemExit(1)

    if fmt == "html":
        dest = project_dir / f"{name}_{ts}.html"
        shutil.copy(html_src, dest)
        console.print(f"[green]Exported → {dest}[/green]")

    elif fmt == "pdf":
        dest = project_dir / f"{name}_{ts}.pdf"
        exporter.to_pdf(html_src, dest)
        console.print(f"[green]Exported → {dest}[/green]")

    elif fmt == "zip":
        import zipfile
        dest = project_dir / f"{name}_{ts}.zip"
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(html_src, "presentation.html")
            if pdf_src.exists():
                zf.write(pdf_src, "presentation.pdf")
        console.print(f"[green]Exported → {dest}[/green]")


cli.add_command(export_cmd)


# ── diff / antar ──────────────────────────────────────────────────────────────

def _diff_impl(folder: str, from_label: str, to_label: str, model: str | None):
    project_dir = Path(folder).resolve()
    meta = json.loads((project_dir / "project.json").read_text())
    project_cfg = cfg.load_project_config(project_dir)
    effective_model = model or meta.get("model") or project_cfg["model"]

    from_hashes = trk.get_files_at_milestone(project_dir, from_label)
    to_hashes = trk.get_files_at_milestone(project_dir, to_label)

    if from_hashes is None:
        console.print(f"[red]Milestone '{from_label}' not found.[/red]")
        raise SystemExit(1)
    if to_hashes is None:
        console.print(f"[red]Milestone '{to_label}' not found.[/red]")
        raise SystemExit(1)

    added = [f for f in to_hashes if f not in from_hashes]
    modified = [f for f in to_hashes
                if f in from_hashes and to_hashes[f] != from_hashes[f]]
    removed = [f for f in from_hashes if f not in to_hashes]

    console.print(
        f"[dim][sarathi][/dim] {from_label} → {to_label}: "
        f"+{len(added)} added, ~{len(modified)} modified, -{len(removed)} removed"
    )

    files = scanner.scan(project_dir)
    output_dir = project_dir / "output"
    output_dir.mkdir(exist_ok=True)
    html_out = output_dir / f"diff_{from_label}_{to_label}.html".replace(" ", "_")

    diff_description = (
        f"Progress report comparing milestone '{from_label}' to '{to_label}'. "
        f"Files added: {added}. Files modified: {modified}. Files removed: {removed}."
    )

    builder.generate(
        project_name=f"{meta['name']} — {from_label} vs {to_label}",
        description=diff_description,
        files=files,
        model=effective_model,
        output_html=html_out,
        project_dir=project_dir,
        theme=project_cfg.get("theme", "dark-gradient"),
        domain_override="diff",
    )
    console.print(f"[green][sarathi] Diff presentation → {html_out}[/green]")


@click.command("diff")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--from", "from_label", required=True, help="Starting milestone label.")
@click.option("--to", "to_label", required=True, help="Ending milestone label.")
@click.option("--model", default=None)
def diff_cmd(folder, from_label, to_label, model):
    """Generate a progress presentation between two milestones. (Sanskrit: antar)"""
    _diff_impl(folder, from_label, to_label, model)


@click.command("antar")
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--from", "from_label", required=True, help="Starting milestone label.")
@click.option("--to", "to_label", required=True, help="Ending milestone label.")
@click.option("--model", default=None)
def antar_cmd(folder, from_label, to_label, model):
    """Generate a progress presentation between two milestones. (antar = difference)"""
    _diff_impl(folder, from_label, to_label, model)


cli.add_command(diff_cmd)
cli.add_command(antar_cmd)


# ── pull ──────────────────────────────────────────────────────────────────────

@click.command("pull")
@click.argument("model_name")
def pull_cmd(model_name):
    """Pull an Ollama model with a progress indicator."""
    import ollama
    console.print(f"[dim]Pulling [bold]{model_name}[/bold]...[/dim]")
    try:
        for progress in ollama.pull(model_name, stream=True):
            status = getattr(progress, "status", "")
            if status:
                console.print(f"[dim]{status}[/dim]", end="\r")
        console.print(f"\n[green]Model [bold]{model_name}[/bold] ready.[/green]")
    except Exception as exc:
        console.print(f"[red]Pull failed: {exc}[/red]")
        raise SystemExit(1)


cli.add_command(pull_cmd)


# ── portfolio ─────────────────────────────────────────────────────────────────

@click.command("portfolio")
@click.option("--port", default=7432, show_default=True, help="Port for the dashboard.")
@click.option("--add", "extra_dirs", multiple=True,
              help="Extra project folders to include in this session.")
def portfolio_cmd(port, extra_dirs):
    """Launch the Sarathi portfolio dashboard at localhost.

    Shows all tracked projects, milestones, and presentation links.
    """
    console.print(
        f"[dim][sarathi][/dim] Starting portfolio dashboard on "
        f"[bold cyan]http://localhost:{port}[/bold cyan]"
    )
    ptf.serve(port=port, extra_dirs=list(extra_dirs))


cli.add_command(portfolio_cmd)
