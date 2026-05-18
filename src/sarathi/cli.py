from __future__ import annotations

import json
import sys
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
from . import setup_wizard
from . import git_context as gitctx
from . import jobs as _jobs

console = Console()

DEFAULT_MODEL = "qwen3.5"


def _spawn_bg(command: str, cli_args: list[str], label: str = "", meta: dict | None = None) -> None:
    """Spawn a sarathi sub-command in the background and print a status line.

    Writes a job entry to ~/.config/sarathi/jobs.json so `sarathi jobs`
    and the portfolio dashboard can track it.
    """
    job = _jobs.new_job(command, label=label, **(meta or {}))
    proc = _jobs.spawn(cli_args + ["--_job-id", job["id"]], log_path=job["log"])
    _jobs.update_job(job["id"], pid=proc.pid, status="running")
    console.print(
        f"[green]⚙  {command}[/green] started in background "
        f"[dim](PID {proc.pid})[/dim]\n"
        f"  [dim]Progress: [cyan]sarathi jobs[/cyan]  "
        f"· Log: [cyan]sarathi logs {job['id']}[/cyan]  "
        f"· Dashboard: [cyan]sarathi portfolio[/cyan][/dim]"
    )

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
    """Sarathi — turn project results into polished presentations.

    \b
    Quick start:
      sarathi setup                          first-time setup
      sarathi init "name" "description"      create a new project
      sarathi join <name or folder>/         join an existing project (reads git history)
      sarathi ls                             list all tracked projects
      sarathi track <name or folder>/        watch + auto-generate on file changes
      sarathi mark <name or folder>/ --name "v1"  plant a milestone
      sarathi viraam                         end-of-session: mark + generate all projects
      sarathi update                         morning briefing + pending changes
      sarathi jobs                           background job queue
      sarathi logs <id or name>              tail a job log
      sarathi portfolio                      dashboard at localhost:7432

    \b
    Sanskrit aliases (same command, different name):
      arambh  = init        yatra   = join      padav   = mark
      bana    = make        safar   = track     viraam  = viraam (no alias needed)
      haal    = status      dekh    = portfolio antar   = diff
      suchi   = ls          vivaran = info

    Run any command with --help for details.
    """


# ── helpers ───────────────────────────────────────────────────────────────────

def _add(english_cmd, sanskrit_cmd):
    cli.add_command(english_cmd)
    cli.add_command(sanskrit_cmd)


def _resolve_folder(name_or_path: str) -> str:
    """Resolve a project name or path to an absolute folder path."""
    import os as _os
    p = Path(_os.path.abspath(name_or_path))
    if p.exists():
        return str(p)
    registry = ptf._load_registry()
    needle = name_or_path.strip().lower()
    for key, info in registry.items():
        reg_name = (info.get("name") or "").lower()
        reg_base = Path(key).name.lower()
        if reg_name == needle or reg_base == needle or key == name_or_path:
            resolved = Path(key)
            if resolved.exists():
                return str(resolved)
            console.print(f"[red]Project '{info.get('name', key)}' is registered but its folder no longer exists:[/red] {key}")
            raise SystemExit(1)
    console.print(
        f"[red]Cannot find project '{name_or_path}'.[/red]\n"
        f"  Use a folder path or a project name from [bold]sarathi ls[/bold]."
    )
    raise SystemExit(1)


# ── init / arambh ─────────────────────────────────────────────────────────────

_DOMAIN_CHOICES = {"ml": "ML / AI", "software": "Software Dev", "data": "Data Analysis", "auto": "Auto-detect"}
_STATUS_CHOICES  = {"active": "Active", "planning": "Planning", "paused": "On Hold", "shipped": "Shipped"}


def _project_wizard(
    project_dir: Path,
    *,
    prefill_name: str = "",
    prefill_desc: str = "",
    model: str = DEFAULT_MODEL,
    existing: bool = False,
) -> dict:
    """Interactive wizard to collect comprehensive project metadata.

    Returns the completed meta dict (does NOT write to disk).
    """
    from rich.prompt import Prompt, Confirm
    from rich.rule import Rule

    console.print()
    console.print(Rule("[bold]Sarathi — New Project Setup[/bold]", style="cyan"))
    console.print()

    # ── Core identity ──────────────────────────────────────────────────────────
    name = Prompt.ask(
        "  [bold cyan]Project name[/bold cyan] [dim](folder slug)[/dim]",
        default=prefill_name or project_dir.name,
    ).strip()

    description = Prompt.ask(
        "  [bold cyan]One-line description[/bold cyan]",
        default=prefill_desc,
    ).strip()

    goal = Prompt.ask(
        "  [bold cyan]Goal / what are you trying to achieve?[/bold cyan] "
        "[dim](longer — shown in portfolio detail)[/dim]",
        default="",
    ).strip()

    # ── Domain ────────────────────────────────────────────────────────────────
    console.print()
    console.print("  [bold cyan]Domain[/bold cyan]")
    for k, v in _DOMAIN_CHOICES.items():
        console.print(f"    [dim]{k}[/dim]  {v}")
    domain = Prompt.ask(
        "  Choose",
        choices=list(_DOMAIN_CHOICES.keys()),
        default="auto",
    )

    # ── Tags ──────────────────────────────────────────────────────────────────
    tags_raw = Prompt.ask(
        "  [bold cyan]Tags[/bold cyan] [dim](comma-separated keywords, e.g. yolov8, pytorch, fastapi)[/dim]",
        default="",
    ).strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    # ── Status ────────────────────────────────────────────────────────────────
    console.print()
    console.print("  [bold cyan]Status[/bold cyan]")
    for k, v in _STATUS_CHOICES.items():
        console.print(f"    [dim]{k}[/dim]  {v}")
    status = Prompt.ask(
        "  Choose",
        choices=list(_STATUS_CHOICES.keys()),
        default="active",
    )

    # ── Links ─────────────────────────────────────────────────────────────────
    repo_url = ""
    if existing:
        # Try to auto-detect git remote
        try:
            import subprocess
            repo_url = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(project_dir), capture_output=True, text=True, timeout=3,
            ).stdout.strip()
        except Exception:
            pass
    if not repo_url:
        repo_url = Prompt.ask(
            "  [bold cyan]Repository URL[/bold cyan] [dim](GitHub / GitLab, optional)[/dim]",
            default="",
        ).strip()

    notes_url = Prompt.ask(
        "  [bold cyan]Related link[/bold cyan] [dim](paper, dataset, Notion page — optional)[/dim]",
        default="",
    ).strip()

    # ── Team ──────────────────────────────────────────────────────────────────
    team = Prompt.ask(
        "  [bold cyan]Team / collaborators[/bold cyan] [dim](names or 'solo')[/dim]",
        default="solo",
    ).strip()

    # ── Model (show current default, offer to change) ─────────────────────────
    console.print()
    pcfg = cfg.load_project_config(project_dir) if existing else {}
    current_model = pcfg.get("model") or model
    change_model = Confirm.ask(
        f"  [bold cyan]Model[/bold cyan]: [dim]{current_model}[/dim]  — change?",
        default=False,
    )
    if change_model:
        current_model = Prompt.ask("  Model name", default=current_model).strip()

    # ── Day-0 milestone ───────────────────────────────────────────────────────
    console.print()
    mark_day0 = Confirm.ask(
        "  Mark a [bold cyan]day-0 milestone[/bold cyan] to record starting state?",
        default=True,
    )
    milestone_label = ""
    if mark_day0:
        milestone_label = Prompt.ask(
            "  Milestone label",
            default="project started",
        ).strip()

    return {
        "name":        name,
        "description": description,
        "goal":        goal,
        "domain":      domain,
        "tags":        tags,
        "status":      status,
        "repo_url":    repo_url,
        "notes_url":   notes_url,
        "team":        team,
        "model":       current_model,
        "created":     datetime.now().isoformat(timespec="seconds"),
        "_milestone":  milestone_label,
    }


def _write_meta_and_init(project_dir: Path, meta: dict) -> None:
    """Write project.json, init tracker, register project, optionally mark milestone."""
    milestone_label = meta.pop("_milestone", "")

    project_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("data", "plots", "notes", "output"):
        (project_dir / sub).mkdir(exist_ok=True)

    (project_dir / "project.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    trk.init_tracker(project_dir)
    trk.log_event(project_dir, "init", name=meta["name"])
    if milestone_label:
        hashes = trk.snapshot_hashes(project_dir)
        trk.log_event(project_dir, "milestone", label=milestone_label, file_hashes=hashes)
    ptf.register_project(project_dir)


def _print_init_summary(meta: dict, project_dir: Path) -> None:
    name   = meta.get("name", project_dir.name)
    domain = _DOMAIN_CHOICES.get(meta.get("domain", "auto"), "Auto-detect")
    tags   = ", ".join(meta.get("tags") or []) or "—"
    status = _STATUS_CHOICES.get(meta.get("status", "active"), "Active")
    goal   = meta.get("goal") or "—"
    team   = meta.get("team") or "solo"
    model  = meta.get("model") or DEFAULT_MODEL

    console.print()
    console.print(Panel(
        f"[bold green]✓  Project '{name}' ready![/bold green]\n\n"
        f"[dim]Description[/dim]  {meta.get('description','')}\n"
        f"[dim]Goal       [/dim]  {goal[:80]}\n"
        f"[dim]Domain     [/dim]  {domain}\n"
        f"[dim]Tags       [/dim]  {tags}\n"
        f"[dim]Status     [/dim]  {status}\n"
        f"[dim]Team       [/dim]  {team}\n"
        f"[dim]Model      [/dim]  {model}\n\n"
        f"Drop your results into:\n"
        f"  [cyan]{project_dir}/data/[/cyan]   — CSV, JSON\n"
        f"  [cyan]{project_dir}/plots/[/cyan]  — PNG, SVG\n"
        f"  [cyan]{project_dir}/notes/[/cyan]  — text, markdown\n\n"
        f"Then run:\n"
        f"  [bold]sarathi track {project_dir.name}/[/bold]",
        title="sarathi init / arambh",
        border_style="green",
    ))


def _init_impl(name: str | None, description: str | None, model: str):
    project_dir = Path(name) if name else Path(".")

    if name and project_dir.exists():
        console.print(f"[red]Folder '{name}' already exists.[/red]")
        raise SystemExit(1)

    if name:
        project_dir = Path(name)

    meta = _project_wizard(
        project_dir,
        prefill_name=name or "",
        prefill_desc=description or "",
        model=model,
        existing=False,
    )

    # Use wizard name as folder if it differs from arg
    if name is None:
        project_dir = Path(meta["name"])
        if project_dir.exists():
            console.print(f"[red]Folder '{meta['name']}' already exists.[/red]")
            raise SystemExit(1)

    _write_meta_and_init(project_dir, meta)
    _print_init_summary(meta, project_dir)


@click.command("init")
@click.argument("name", required=False, default=None)
@click.argument("description", required=False, default=None)
@click.option("--model", default=DEFAULT_MODEL, show_default=True,
              help="Ollama model to use for generation.")
def init_cmd(name, description, model):
    """Create a new project folder with data/, plots/, and notes/ subdirs.

    Run without arguments for the full interactive wizard:
      sarathi init

    Or pass name and description to pre-fill:
      sarathi init my-project "Training a YOLOv8 detector"
    """
    _init_impl(name, description, model)


@click.command("arambh", hidden=True)
@click.argument("name", required=False, default=None)
@click.argument("description", required=False, default=None)
@click.option("--model", default=DEFAULT_MODEL, show_default=True,
              help="Ollama model to use for generation.")
def arambh_cmd(name, description, model):
    """Create a new project folder. (arambh = beginning)"""
    _init_impl(name, description, model)


cli.add_command(init_cmd)
cli.add_command(arambh_cmd)


# ── track / yatra ─────────────────────────────────────────────────────────────

def _track_impl(folder: str, once: bool, model: str | None, edit_outline: bool,
                verbose: bool = False, fast: bool = False, offload: bool = False,
                job_id: str = ""):
    project_dir = Path(folder)
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

    project_cfg    = cfg.load_project_config(project_dir)
    effective_model = model or meta.get("model") or project_cfg["model"]
    planner_model  = project_cfg.get("planner_model")
    coder_model    = project_cfg.get("coder_model")
    vision_model   = project_cfg.get("vision_model")
    fast_model     = project_cfg.get("fast_model")
    theme          = project_cfg.get("theme", "dark-gradient")
    cloud_api_url  = project_cfg.get("cloud_api_url", "")
    cloud_api_key  = project_cfg.get("cloud_api_key", "")
    output_dir = project_dir / "output"
    output_dir.mkdir(exist_ok=True)

    milestones = trk.get_milestones(project_dir)
    last_gen = trk.last_generated(project_dir)
    console.print(
        f"[dim][sarathi][/dim] Tracking [bold]{meta['name']}[/bold] — "
        f"{len(milestones)} milestone(s), last generated: {last_gen or 'never'}"
    )

    # Git context — extracted once and reused across all generate() calls
    git_ctx = gitctx.extract(project_dir)
    if git_ctx:
        gitctx.print_summary(git_ctx, console)
    git_ctx_text = gitctx.format_for_llm(git_ctx) if git_ctx else None

    outline_path = (project_dir / ".sarathi" / "outline.json") if edit_outline else None

    def generate():
        console.print(f"[dim][sarathi][/dim] Scanning {project_dir.name}...")
        files = scanner.scan(project_dir)

        if not files:
            console.print("[yellow][sarathi] No result files found yet — waiting.[/yellow]")
            return

        trk.log_event(project_dir, "checkpoint",
                      file_hashes=trk.snapshot_hashes(project_dir))

        # Determine which model will actually be used
        _display_model = (
            fast_model or effective_model if fast
            else f"{planner_model or effective_model} + {coder_model or effective_model}"
        )
        console.print(
            f"[dim][sarathi][/dim] Found {len(files)} file(s) — "
            f"{'[cyan]fast[/cyan]' if fast else '[cyan]two-pass[/cyan]'} · "
            f"[bold]{_display_model}[/bold]"
        )

        if offload:
            from .setup_wizard import _unload_all
            console.print("[dim][sarathi] Offloading models from RAM...[/dim]", end="\r")
            _unload_all()
            console.print("[dim][sarathi] RAM cleared.                [/dim]")

        html_out = output_dir / "presentation.html"
        pdf_out = output_dir / "presentation.pdf"

        if edit_outline and outline_path and not outline_path.exists():
            console.print(
                f"\n[yellow][sarathi] Pass 1 will save outline to "
                f"[bold].sarathi/outline.json[/bold].\n"
                f"Edit it, then re-run without --edit-outline to render slides.[/yellow]\n"
            )

        try:
            if job_id:
                _jobs.update_job(job_id, status="running", current=project_dir.name)

            # Detect if there's a new milestone since last generation → include recap
            delta = trk.get_delta_since_last_milestone(project_dir)
            if delta:
                v_next = trk.get_next_version(project_dir)
                console.print(
                    f"[dim][sarathi][/dim] New milestone detected — "
                    f"generating [bold]v{v_next}[/bold] with recap slide "
                    f"(since \"{delta.get('prev_milestone','')}\")"
                )

            trk.write_status(project_dir, state="generating", model=effective_model)
            gen_stats = builder.generate(
                project_name=meta["name"],
                description=meta["description"],
                files=files,
                model=effective_model,
                output_html=html_out,
                project_dir=project_dir,
                theme=theme,
                outline_path=outline_path,
                git_ctx_text=git_ctx_text,
                verbose=verbose,
                fast=fast,
                planner_model=planner_model,
                coder_model=coder_model,
                vision_model=vision_model,
                fast_model=fast_model,
                delta=delta or None,
                cloud_api_url=cloud_api_url,
                cloud_api_key=cloud_api_key,
            ) or {}
            trk.write_status(project_dir, state="idle")
            trk.log_event(project_dir, "generated",
                          html=str(html_out.relative_to(project_dir)),
                          model=effective_model,
                          tok_s=gen_stats.get("tok_s", 0),
                          duration_s=gen_stats.get("duration_s", 0),
                          slide_count=gen_stats.get("slide_count", 0),
                          mode=gen_stats.get("mode", "unknown"))
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

    import os as _os
    trk.write_pid(project_dir, _os.getpid())
    try:
        console.print(
            f"\n[dim][sarathi] Watching {project_dir.name}/ for changes "
            "(Ctrl+C to stop)...[/dim]"
        )
        watcher.watch(project_dir, generate)
    finally:
        trk.clear_pid(project_dir)
        trk.write_status(project_dir, state="idle")


@click.command("track")
@click.argument("folder", type=str)
@click.option("--once", is_flag=True, help="Generate once and exit.")
@click.option("--model", default=None, help="Override the Ollama model.")
@click.option("--edit-outline", is_flag=True,
              help="Save JSON outline for editing before rendering slides.")
@click.option("--fast", is_flag=True,
              help="Single-pass generation (faster but lower quality). Default is two-pass.")
@click.option("--offload", is_flag=True,
              help="Unload all Ollama models from RAM before generating.")
@click.option("--verbose", "-v", is_flag=True,
              help="Print every prompt sent to the LLM and its raw response.")
@click.option("--bg", is_flag=True,
              help="Run watcher in background — returns immediately, logs to ~/.config/sarathi/logs/.")
@click.option("--_job-id", "job_id", default="", hidden=True)
def track_cmd(folder, once, model, edit_outline, fast, offload, verbose, bg, job_id):
    """Watch a project folder and regenerate on every file change."""
    folder = _resolve_folder(folder)
    if bg:
        args = ["track", folder]
        if once:         args += ["--once"]
        if model:        args += ["--model", model]
        if edit_outline: args += ["--edit-outline"]
        if fast:         args += ["--fast"]
        if offload:      args += ["--offload"]
        _spawn_bg("track", args, label=folder, meta={"project": folder})
        return
    _track_impl(folder, once, model, edit_outline, verbose=verbose,
                fast=fast, offload=offload, job_id=job_id)


@click.command("yatra", hidden=True)
@click.argument("folder", type=str)
@click.option("--once", is_flag=True)
@click.option("--model", default=None)
@click.option("--edit-outline", is_flag=True)
@click.option("--fast", is_flag=True)
@click.option("--offload", is_flag=True)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--bg", is_flag=True)
@click.option("--_job-id", "job_id", default="", hidden=True)
def yatra_cmd(folder, once, model, edit_outline, fast, offload, verbose, bg, job_id):
    """Join an existing project and generate a presentation. (yatra = journey)"""
    folder = _resolve_folder(folder)
    join_cmd.callback(folder=folder, model=model, once=once, fast=fast,
                      offload=offload, verbose=verbose, bg=bg)


cli.add_command(track_cmd)
cli.add_command(yatra_cmd)


# ── make / bana ───────────────────────────────────────────────────────────────

@click.command("make")
@click.argument("folder", type=str)
@click.option("--model", default=None, help="Override the Ollama model.")
@click.option("--edit-outline", is_flag=True)
@click.option("--fast", is_flag=True,
              help="Single-pass generation (faster but lower quality). Default is two-pass.")
@click.option("--offload", is_flag=True,
              help="Unload all Ollama models from RAM before generating.")
@click.option("--verbose", "-v", is_flag=True,
              help="Print every prompt and raw LLM response.")
@click.option("--bg", is_flag=True,
              help="Generate in background — returns immediately.")
@click.option("--_job-id", "job_id", default="", hidden=True)
def make_cmd(folder, model, edit_outline, fast, offload, verbose, bg, job_id):
    """Generate a presentation once and exit (no watching)."""
    folder = _resolve_folder(folder)
    if bg:
        args = ["make", folder, "--once"]
        if model:        args += ["--model", model]
        if fast:         args += ["--fast"]
        if offload:      args += ["--offload"]
        _spawn_bg("make", args, label=folder, meta={"project": folder})
        return
    _track_impl(folder, True, model, edit_outline, verbose=verbose,
                fast=fast, offload=offload, job_id=job_id)


@click.command("bana", hidden=True)
@click.argument("folder", type=str)
@click.option("--model", default=None)
@click.option("--edit-outline", is_flag=True)
@click.option("--fast", is_flag=True)
@click.option("--offload", is_flag=True)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--bg", is_flag=True)
@click.option("--_job-id", "job_id", default="", hidden=True)
def bana_cmd(folder, model, edit_outline, fast, offload, verbose, bg, job_id):
    """Generate a presentation once and exit. (bana = build)"""
    folder = _resolve_folder(folder)
    if bg:
        _spawn_bg("make", ["bana", folder] + (["--fast"] if fast else []),
                  label=folder, meta={"project": folder})
        return
    _track_impl(folder, True, model, edit_outline, verbose=verbose,
                fast=fast, offload=offload, job_id=job_id)


cli.add_command(make_cmd)
cli.add_command(bana_cmd)


# ── mark / chinh ──────────────────────────────────────────────────────────────

def _mark_impl(folder: str, name: str):
    project_dir = Path(folder)
    trk.init_tracker(project_dir)
    hashes = trk.snapshot_hashes(project_dir)
    trk.log_event(project_dir, "milestone", label=name, file_hashes=hashes)

    # Snapshot current output as a versioned copy
    vdir = trk.snapshot_output_version(project_dir, name)
    if vdir:
        n = trk.get_next_version(project_dir) - 1  # already incremented by snapshot
        console.print(
            f"[green][sarathi] ★ Milestone [bold]\"{name}\"[/bold] marked.[/green]\n"
            f"[dim]  → Presentation archived as [bold]v{n}[/bold] in {vdir.relative_to(project_dir)}[/dim]"
        )
    else:
        console.print(
            f"[green][sarathi] ★ Milestone [bold]\"{name}\"[/bold] marked.[/green]\n"
            f"[dim]  (No presentation to archive yet — run sarathi track first)[/dim]"
        )


@click.command("mark")
@click.argument("folder", type=str)
@click.option("--name", required=True, help="Milestone label.")
def mark_cmd(folder, name):
    """Plant a named milestone in the project timeline.

    Snapshots the current file state so you can diff or regenerate at this point later.
    """
    folder = _resolve_folder(folder)
    _mark_impl(folder, name)


@click.command("padav", hidden=True)
@click.argument("folder", type=str)
@click.option("--name", required=True, help="Milestone label.")
def padav_cmd(folder, name):
    """Plant a named milestone in the timeline. (padav = waypoint)"""
    folder = _resolve_folder(folder)
    _mark_impl(folder, name)


cli.add_command(mark_cmd)
cli.add_command(padav_cmd)


# ── log / itihas ──────────────────────────────────────────────────────────────

def _log_impl(folder: str):
    project_dir = Path(folder)
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
@click.argument("folder", type=str)
def log_cmd(folder):
    """Print the full project timeline — file events, checkpoints, and milestones."""
    folder = _resolve_folder(folder)
    _log_impl(folder)


@click.command("safar", hidden=True)
@click.argument("folder", type=str)
@click.option("--once", is_flag=True)
@click.option("--model", default=None)
@click.option("--edit-outline", is_flag=True)
@click.option("--fast", is_flag=True)
@click.option("--offload", is_flag=True)
@click.option("--verbose", "-v", is_flag=True)
@click.option("--bg", is_flag=True)
@click.option("--_job-id", "job_id", default="", hidden=True)
def safar_cmd(folder, once, model, edit_outline, fast, offload, verbose, bg, job_id):
    """Watch a project folder and regenerate on every file change. (safar = journey/travel)"""
    folder = _resolve_folder(folder)
    if bg:
        args = ["safar", folder] + (["--once"] if once else []) + (["--fast"] if fast else [])
        _spawn_bg("track", args, label=folder, meta={"project": folder})
        return
    _track_impl(folder, once, model, edit_outline, verbose=verbose,
                fast=fast, offload=offload, job_id=job_id)


cli.add_command(log_cmd)
cli.add_command(safar_cmd)


# ── status / sthiti ───────────────────────────────────────────────────────────

def _status_impl(folder: str):
    project_dir = Path(folder)
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
@click.argument("folder", type=str)
def status_cmd(folder):
    """Show model, theme, last generation time, and files changed since then."""
    folder = _resolve_folder(folder)
    _status_impl(folder)


@click.command("haal", hidden=True)
@click.argument("folder", type=str)
def haal_cmd(folder):
    """Show current project state. (haal = current state)"""
    folder = _resolve_folder(folder)
    _status_impl(folder)


cli.add_command(status_cmd)
cli.add_command(haal_cmd)


# ── open / darshan ────────────────────────────────────────────────────────────

def _open_impl(folder: str):
    project_dir = Path(folder)
    html = project_dir / "output" / "presentation.html"
    if not html.exists():
        console.print("[red]No presentation.html found. Run sarathi make first.[/red]")
        raise SystemExit(1)
    webbrowser.open(html.as_uri())
    console.print(f"[green]Opened {html}[/green]")


@click.command("open")
@click.argument("folder", type=str)
def open_cmd(folder):
    """Open output/presentation.html in the default browser."""
    folder = _resolve_folder(folder)
    _open_impl(folder)


@click.command("dekh", hidden=True)
@click.option("--port", default=7432)
@click.option("--dir", "extra_dirs", multiple=True)
def dekh_cmd(port, extra_dirs):
    """Launch the portfolio dashboard. (dekh = look/see)"""
    portfolio_cmd.callback(port=port, extra_dirs=extra_dirs)


cli.add_command(open_cmd)
cli.add_command(dekh_cmd)


# ── clean ─────────────────────────────────────────────────────────────────────

@click.command("clean")
@click.argument("folder", type=str)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def clean_cmd(folder, yes):
    """Delete output/ and .sarathi/viz/ to force a clean regeneration."""
    folder = _resolve_folder(folder)
    project_dir = Path(folder)
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
@click.option("--benchmark", "-b", is_flag=True,
              help="Run a quick speed test on each pulled model (tok/s).")
@click.option("--verbose", "-v", is_flag=True,
              help="Show prompt, full response, and per-phase timing for each model.")
def models_cmd(benchmark, verbose):
    """List Ollama models on this machine, flagging vision-capable ones."""
    import shutil, ollama

    try:
        result = ollama.list()
    except Exception as exc:
        console.print(f"[red]Could not connect to Ollama: {exc}[/red]")
        raise SystemExit(1)

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Model")
    table.add_column("Size", justify="right")
    table.add_column("Vision", justify="center")
    if benchmark:
        table.add_column("Gen speed",  justify="right")
        table.add_column("Load time",  justify="right")
        table.add_column("Tokens",     justify="right")

    for m in result.models:
        name     = m.model
        size_gb  = f"{m.size / 1e9:.1f} GB" if hasattr(m, "size") and m.size else "—"
        cap      = "[magenta]vision[/magenta]" if _is_vision(name) else "[dim]—[/dim]"
        row      = [name, size_gb, cap]

        if benchmark:
            try:
                from .setup_wizard import benchmark_model
                if not verbose:
                    console.print(f"[dim]  Benchmarking {name}...[/dim]", end="\r")
                r       = benchmark_model(name, verbose=verbose)
                if not r["ok"]:
                    row += [f"[red]{str(r.get('error',''))[:20]}[/red]", "—", "—"]
                else:
                    tps_val = r["tps"]
                    load_s  = r.get("load_s", 0)
                    tokens  = r.get("eval_tokens", 0)
                    color   = "green" if tps_val >= 5 else "yellow" if tps_val >= 2 else "red"
                    row += [
                        f"[{color}]{tps_val:.1f} tok/s[/{color}]",
                        f"[dim]{load_s:.1f}s[/dim]",
                        f"[dim]{tokens}[/dim]",
                    ]
            except Exception as e:
                row += [f"[red]error[/red]", "—", "—"]

        table.add_row(*row)

    console.print(table)
    if benchmark:
        console.print(
            "\n[dim]Gen speed = tokens/s after model is loaded (warmup run done first).\n"
            "Load time = cold-start time (first request only, then cached).\n"
            "  ≥ 10 tok/s → fast  (~2-5 min per presentation)\n"
            "  2–10 tok/s → usable (~10-30 min per presentation)\n"
            "  < 2 tok/s  → slow  (consider a cloud model instead)[/dim]"
        )
    console.print(
        "\n[dim]For fast generation without local RAM: [bold]ollama pull kimi-k2.5:cloud[/bold]\n"
        "Recommended local: [bold]qwen3.5[/bold] · Recommended cloud: [bold]kimi-k2.5:cloud[/bold][/dim]"
    )


cli.add_command(models_cmd)


# ── theme ─────────────────────────────────────────────────────────────────────

THEMES = ["dark-gradient", "dracula", "light", "minimal"]


@click.command("theme")
@click.argument("folder", type=str)
@click.option("--set", "theme_name", type=click.Choice(THEMES), required=True,
              help="Theme name.")
def theme_cmd(folder, theme_name):
    """Set the presentation theme for a project."""
    folder = _resolve_folder(folder)
    project_dir = Path(folder)
    trk.init_tracker(project_dir)
    cfg.save_project_config(project_dir, {"theme": theme_name})
    console.print(f"[green]Theme set to [bold]{theme_name}[/bold].[/green]")


cli.add_command(theme_cmd)


# ── export ────────────────────────────────────────────────────────────────────

@click.command("export")
@click.argument("folder", type=str)
@click.option("--format", "fmt", type=click.Choice(["html", "pdf", "zip"]),
              default="pdf", show_default=True)
def export_cmd(folder, fmt):
    """Re-export the presentation without re-generating."""
    folder = _resolve_folder(folder)
    import shutil
    project_dir = Path(folder)
    html_src = project_dir / "output" / "presentation.html"
    pdf_src = project_dir / "output" / "presentation.pdf"
    name = json.loads((project_dir / "project.json").read_text())["name"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not html_src.exists():
        console.print("[red]No presentation.html found. Run sarathi make first.[/red]")
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
    project_dir = Path(folder)
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
        cloud_api_url=project_cfg.get("cloud_api_url", ""),
        cloud_api_key=project_cfg.get("cloud_api_key", ""),
    )
    console.print(f"[green][sarathi] Diff presentation → {html_out}[/green]")


@click.command("diff")
@click.argument("folder", type=str)
@click.option("--from", "from_label", required=True, help="Starting milestone label.")
@click.option("--to", "to_label", required=True, help="Ending milestone label.")
@click.option("--model", default=None)
def diff_cmd(folder, from_label, to_label, model):
    """Generate a "what changed" presentation between two milestones."""
    folder = _resolve_folder(folder)
    _diff_impl(folder, from_label, to_label, model)


@click.command("antar", hidden=True)
@click.argument("folder", type=str)
@click.option("--from", "from_label", required=True, help="Starting milestone label.")
@click.option("--to", "to_label", required=True, help="Ending milestone label.")
@click.option("--model", default=None)
def antar_cmd(folder, from_label, to_label, model):
    """Generate a progress presentation between two milestones. (antar = difference)"""
    folder = _resolve_folder(folder)
    _diff_impl(folder, from_label, to_label, model)


cli.add_command(diff_cmd)
cli.add_command(antar_cmd)


# ── pull ──────────────────────────────────────────────────────────────────────

@click.command("pull")
@click.argument("model_name")
def pull_cmd(model_name):
    """Download an Ollama model. Recommended: kimi-k2.5:cloud or qwen3.5."""
    import subprocess
    console.print(f"[dim]Pulling [bold]{model_name}[/bold]...[/dim]")
    try:
        result = subprocess.run(["ollama", "pull", model_name])
        if result.returncode == 0:
            console.print(f"[green]Model [bold]{model_name}[/bold] ready.[/green]")
        else:
            console.print(f"[red]Pull failed for {model_name}.[/red]")
            raise SystemExit(1)
    except FileNotFoundError:
        console.print("[red]ollama not found. Run: sarathi setup[/red]")
        raise SystemExit(1)


cli.add_command(pull_cmd)


# ── portfolio ─────────────────────────────────────────────────────────────────

@click.command("portfolio")
@click.option("--port", default=7432, show_default=True, help="Port for the dashboard.")
@click.option("--add", "extra_dirs", multiple=True,
              help="Extra project folders to include in this session.")
def portfolio_cmd(port, extra_dirs):
    """Launch a dashboard showing all projects, milestones, and output links."""
    console.print(
        f"[dim][sarathi][/dim] Starting portfolio dashboard on "
        f"[bold cyan]http://localhost:{port}[/bold cyan]"
    )
    ptf.serve(port=port, extra_dirs=list(extra_dirs))


cli.add_command(portfolio_cmd)


# ── setup ─────────────────────────────────────────────────────────────────────

@click.command("setup")
def setup_cmd():
    """Interactive setup: detect hardware, pick and pull models, configure Sarathi."""
    setup_wizard.run()


cli.add_command(setup_cmd)


# ── info / vivaran ────────────────────────────────────────────────────────────

@click.command("info")
def info_cmd():
    """Show current Sarathi setup — models, Ollama, projects, paths."""
    from rich.rule import Rule
    from importlib.metadata import version as _pkg_version

    try:
        ver = _pkg_version("sarathi")
    except Exception:
        ver = "dev"

    _gcfg_path = Path.home() / ".config" / "sarathi" / "config.json"
    pcfg = {**cfg.DEFAULTS, **(json.loads(_gcfg_path.read_text()) if _gcfg_path.exists() else {})}

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_ok = False
    loaded_model = None
    available: list[str] = []
    try:
        import ollama as _ol
        available = [m.model for m in _ol.list().models]
        ps = _ol.ps()
        loaded = getattr(ps, "models", []) or []
        if loaded:
            loaded_model = getattr(loaded[0], "model", None)
        ollama_ok = True
    except Exception:
        pass

    # ── Projects ──────────────────────────────────────────────────────────────
    registry = ptf._load_registry()
    n_projects = len(registry)

    # ── Jobs ──────────────────────────────────────────────────────────────────
    worker_up = _jobs.is_worker_running()
    queue_len  = _jobs.queue_length()

    # ── Paths ─────────────────────────────────────────────────────────────────
    config_dir = Path.home() / ".config" / "sarathi"
    config_file = config_dir / "config.json"

    console.print()
    console.print(Rule("[bold]Sarathi — vivaran[/bold]", style="cyan"))
    console.print()

    # Version + paths
    console.print(f"  [bold cyan]Version[/bold cyan]      sarathi {ver}")
    console.print(f"  [bold cyan]Config[/bold cyan]       {config_file}")
    console.print(f"  [bold cyan]Logs[/bold cyan]         {config_dir / 'logs'}")
    console.print()

    # Models
    console.print(f"  [bold cyan]Models[/bold cyan]")
    roles = [
        ("Planner",  pcfg.get("planner_model") or pcfg.get("model") or "—"),
        ("Coder",    pcfg.get("coder_model")   or pcfg.get("model") or "—"),
        ("Vision",   pcfg.get("vision_model")  or "—"),
        ("Fast",     pcfg.get("fast_model")    or "—"),
    ]
    # Normalize: strip :latest so "qwen3.5" matches "qwen3.5:latest"
    avail_norm = {m.split(":")[0] if m.endswith(":latest") else m for m in available}
    for role, model in roles:
        model_norm = model.split(":")[0] if model.endswith(":latest") else model
        pulled = model in available or model_norm in avail_norm
        in_ol = "  [green]✓[/green]" if pulled else "  [dim]not pulled[/dim]"
        console.print(f"    [dim]{role:<10}[/dim] {model}{in_ol}")
    console.print()

    # Ollama
    dot = "[green]●[/green]" if ollama_ok else "[red]●[/red]"
    status_str = "running" if ollama_ok else "not reachable"
    console.print(f"  [bold cyan]Ollama[/bold cyan]       {dot} {status_str}")
    if loaded_model:
        console.print(f"  [bold cyan]Loaded[/bold cyan]       {loaded_model}")
    console.print(f"  [bold cyan]Available[/bold cyan]    {len(available)} model(s) pulled")
    console.print()

    # Projects + queue
    console.print(f"  [bold cyan]Projects[/bold cyan]     {n_projects} tracked")
    worker_str = "[green]running[/green]" if worker_up else "[dim]idle[/dim]"
    console.print(f"  [bold cyan]Worker[/bold cyan]       {worker_str}  ·  {queue_len} queued")
    console.print()


cli.add_command(info_cmd)


@click.command("vivaran", hidden=True)
def vivaran_cmd():
    """Show current Sarathi setup. (vivaran = details/description)"""
    info_cmd.callback()


cli.add_command(vivaran_cmd)


# ── join ──────────────────────────────────────────────────────────────────────

@click.command("join")
@click.argument("folder", type=str)
@click.option("--model", default=None, help="Override the Ollama model.")
@click.option("--once", is_flag=True, help="Generate once and exit.")
@click.option("--fast", is_flag=True,
              help="Single-pass generation (faster but lower quality). Default is two-pass.")
@click.option("--offload", is_flag=True,
              help="Unload all Ollama models from RAM before generating.")
@click.option("--verbose", "-v", is_flag=True,
              help="Print every prompt and raw LLM response.")
@click.option("--bg", is_flag=True,
              help="Queue generation in background after setup — returns immediately.")
def join_cmd(folder, model, once, fast, offload, verbose, bg):
    """Join an existing project — reads git history and local changes as context.

    \b
    Use this when you're picking up a project that already has work done:
      sarathi join my-project/        scan git log, diff, files → generate
      sarathi join my-project/ --once generate once and exit
    \b
    Sarathi will read:
      - git log (last 30 commits, commit messages, dates)
      - uncommitted changes (git diff)
      - most actively changed files
      - all result files (images, CSVs, notes, code)
    and build a presentation that tells the story of where the project is now.
    """
    folder = _resolve_folder(folder)
    project_dir = Path(folder)

    # Auto-create project.json if missing (joining a non-sarathi project)
    meta_path = project_dir / "project.json"
    if not meta_path.exists():
        console.print(
            f"\n[dim][sarathi][/dim] No project.json found — "
            "running setup wizard to register this project.\n"
        )
        meta = _project_wizard(
            project_dir,
            prefill_name=project_dir.name,
            model=model or DEFAULT_MODEL,
            existing=True,
        )
        _write_meta_and_init(project_dir, meta)
        _print_init_summary(meta, project_dir)
        console.print()

    if bg:
        project_dir = Path(folder)
        _jobs.enqueue(str(project_dir), fast=fast, model=model or "", offload=offload, label="join")
        started = _jobs.start_worker_if_idle()
        console.print(
            f"\n[green]⚙  Generation queued in background.[/green]\n"
            f"[dim]  sarathi jobs      — check progress\n"
            f"  sarathi portfolio — live dashboard[/dim]"
        )
        return
    _track_impl(folder, once, model, edit_outline=False, verbose=verbose, fast=fast, offload=offload)


cli.add_command(join_cmd)


# ── update / navakar ──────────────────────────────────────────────────────────

def _update_impl():
    """Morning briefing: show what background jobs ran and what's pending."""
    from datetime import timedelta

    console.print()
    console.print("[bold]Sarathi — Morning Report[/bold]")
    console.print()

    # ── Background jobs since yesterday ──────────────────────────────────────
    since = (datetime.now() - timedelta(hours=16)).isoformat(timespec="seconds")
    recent = _jobs.get_recent_jobs(since_iso=since, limit=20)

    generated = [j for j in recent if j.get("status") == "done"]
    failed     = [j for j in recent if j.get("status") in ("failed", "interrupted")]
    running    = [j for j in recent if j.get("status") == "running"]
    queued     = _jobs.get_queue()

    if generated:
        console.print(f"[green]⚡ Generated overnight[/green]")
        for j in generated:
            name = Path(j.get("project", "?")).name
            ts   = j.get("started", "")[:16].replace("T", " ")
            console.print(f"  [cyan]{name:<22}[/cyan] [dim]{ts}[/dim]")
        console.print()

    if failed:
        console.print(f"[red]✗ Failed[/red]")
        for j in failed:
            name = Path(j.get("project", "?")).name
            console.print(f"  [red]{name}[/red]  → sarathi logs {j['id']}")
        console.print()

    if running:
        console.print(f"[yellow]⚙ Still running[/yellow]")
        for j in running:
            name = Path(j.get("project", "?")).name
            console.print(f"  [yellow]{name}[/yellow]")
        console.print()

    if queued:
        console.print(f"[dim]Queue ({len(queued)} pending)[/dim]")
        for j in queued:
            name = Path(j.get("project", "?")).name
            console.print(f"  [dim]{name}[/dim]")
        console.print()

    # ── Project status ────────────────────────────────────────────────────────
    registry = ptf._load_registry()
    pending_projects = []
    uptodate_projects = []
    for info in registry.values():
        p = Path(info["path"])
        if not p.exists():
            continue
        if trk.files_since_last_generated(p):
            pending_projects.append(p)
        else:
            uptodate_projects.append(p)

    if pending_projects:
        console.print(f"[amber]⚠ Pending — files changed since last deck[/amber]".replace("amber", "yellow"))
        for p in pending_projects:
            n = len(trk.files_since_last_generated(p))
            console.print(f"  [yellow]{p.name:<22}[/yellow] {n} file(s) changed")
        console.print()

    if uptodate_projects:
        console.print(f"[green]✓ Up to date[/green]")
        for p in uptodate_projects:
            last = trk.last_generated(p)
            ts   = last[:16].replace("T", " ") if last else "never"
            console.print(f"  [dim]{p.name:<22}  {ts}[/dim]")
        console.print()

    if not generated and not pending_projects and not queued:
        console.print("[dim]Nothing to report. Run sarathi viraam at the end of your session.[/dim]")
    elif pending_projects:
        console.print(
            f"[dim]Run [bold]sarathi viraam --bg[/bold] to mark milestones and queue generation.[/dim]"
        )

    worker_status = "running" if _jobs.is_worker_running() else "idle"
    console.print(f"\n[dim]Queue worker: {worker_status}[/dim]")


@click.command("update")
def update_cmd():
    """Morning briefing: show background job results and pending projects.

    Run this when you sit down in the morning. It shows what generated
    overnight, what failed, and what still needs a deck.
    """
    _update_impl()


@click.command("navakar", hidden=True)
def navakar_cmd():
    """Morning briefing — shows overnight job results. (navakar = renewal)"""
    _update_impl()


cli.add_command(update_cmd)
cli.add_command(navakar_cmd)


# ── viraam ────────────────────────────────────────────────────────────────────

def _viraam_impl(milestone_name: str, fast: bool, offload: bool, model: str | None,
                 job_id: str = ""):
    """End-of-session: mark milestones and queue generation for pending projects."""
    label = milestone_name or f"session {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    registry = ptf._load_registry()

    if not registry:
        console.print("[yellow]No projects registered.[/yellow]")
        if job_id:
            _jobs.update_job(job_id, status="done")
        return

    active = [(k, Path(info["path"])) for k, info in registry.items()
              if Path(info["path"]).exists()]

    console.print(Panel(
        f"[bold cyan]viraam[/bold cyan] — end of session\n\n"
        f"Marking milestone [bold]\"{label}\"[/bold] on {len(active)} project(s)\n"
        f"then generating presentations for all.",
        border_style="cyan",
    ))
    console.print()

    # Step 1: mark milestones on all projects with changes (fast, no LLM)
    needs_generation = []
    for _, project_dir in active:
        pending = trk.files_since_last_generated(project_dir)
        trk.init_tracker(project_dir)
        hashes = trk.snapshot_hashes(project_dir)
        trk.log_event(project_dir, "milestone", label=label, file_hashes=hashes)
        if pending:
            trk.snapshot_output_version(project_dir, label)
            console.print(f"  [green]★[/green] {project_dir.name} — milestone + snapshot ({len(pending)} file(s) changed)")
            needs_generation.append(project_dir)
        else:
            console.print(f"  [dim]★ {project_dir.name} — milestone (up to date, no regen needed)[/dim]")

    console.print()

    if not needs_generation:
        console.print(Panel(
            f"[bold green]✓ viraam complete[/bold green]\n\n"
            f"Milestone [bold]\"{label}\"[/bold] marked on all {len(active)} project(s).\n"
            f"All projects are up to date — no generation needed.",
            border_style="green",
        ))
        return

    # Step 2: enqueue generation for projects that have pending changes
    for project_dir in needs_generation:
        _jobs.enqueue(str(project_dir), fast=fast, model=model or "", offload=offload, label=label)
        console.print(f"  [cyan]⚙[/cyan] {project_dir.name} — queued for generation")

    # Step 3: start the queue worker if not already running
    started = _jobs.start_worker_if_idle()

    n = len(needs_generation)
    worker_note = "Queue worker started." if started else "Worker already running — jobs added to queue."
    console.print()
    console.print(Panel(
        f"[bold green]✓ viraam complete[/bold green]\n\n"
        f"Milestone [bold]\"{label}\"[/bold] marked on all {len(active)} project(s).\n"
        f"{n} project(s) queued for generation in background.\n\n"
        f"{worker_note}\n"
        f"Track progress: [cyan]sarathi jobs[/cyan]  ·  Dashboard: [cyan]sarathi portfolio[/cyan]",
        border_style="green",
    ))


@click.command("viraam")
@click.option("--name", default="", help="Milestone label (default: session timestamp).")
@click.option("--fast", is_flag=True, help="Use fast model for all projects.")
@click.option("--offload", is_flag=True, help="Unload models between projects.")
@click.option("--model", default=None, help="Override model for all projects.")
def viraam_cmd(name, fast, offload, model):
    """End-of-session: mark milestones, queue generation for pending projects.

    \b
    viraam (Sanskrit: pause/rest) — run at the end of your work session.
    Milestones are marked immediately (fast).
    Generation runs in the background queue — one project at a time.
    Check progress tomorrow morning with: sarathi update
    """
    _viraam_impl(milestone_name=name, fast=fast, offload=offload, model=model)


cli.add_command(viraam_cmd)


# ── Queue worker (hidden internal command) ────────────────────────────────────

@click.command("_worker", hidden=True)
@click.option("--worker-log", default="", help="Path to this worker's log file.")
def worker_cmd(worker_log):
    """Internal: drain the generation queue one project at a time."""
    import os as _os
    _jobs._write_worker_pid(_os.getpid())
    console = Console(stderr=True)  # log to stderr so it goes to the log file

    console.print(f"[dim][worker] Queue worker started (PID {_os.getpid()})[/dim]")

    try:
        while True:
            job = _jobs.dequeue()
            if not job:
                console.print("[dim][worker] Queue empty — exiting.[/dim]")
                break

            project_dir = job.get("project", "")
            if not project_dir or not Path(project_dir).exists():
                _jobs.finish_queued(job["id"], status="failed")
                console.print(f"[red][worker] Project not found: {project_dir}[/red]")
                continue

            console.print(f"[dim][worker] Generating: {Path(project_dir).name}[/dim]")
            _jobs.update_job(job["id"], status="running", pid=_os.getpid(),
                             started=datetime.now().isoformat(timespec="seconds"),
                             **({"log": worker_log} if worker_log else {}))

            try:
                _track_impl(
                    project_dir, once=True, model=job.get("model") or None,
                    edit_outline=False, fast=bool(job.get("fast")),
                    offload=bool(job.get("offload")),
                )
                _jobs.finish_queued(job["id"], status="done")
                console.print(f"[green][worker] Done: {Path(project_dir).name}[/green]")
            except Exception as exc:
                _jobs.finish_queued(job["id"], status="failed")
                console.print(f"[red][worker] Failed {Path(project_dir).name}: {exc}[/red]")
    finally:
        _jobs.clear_worker_pid()
        console.print("[dim][worker] Worker exiting.[/dim]")


cli.add_command(worker_cmd)


# ── jobs / logs / kill ────────────────────────────────────────────────────────

@click.command("jobs")
@click.option("--all", "show_all", is_flag=True, help="Show full history, not just recent.")
def jobs_cmd(show_all):
    """Show background job queue and recent job history."""
    from rich.table import Table as _Table

    queue = _jobs.get_queue()
    recent = _jobs.get_all_jobs(limit=20) if show_all else _jobs.get_recent_jobs(limit=15)

    worker_status = "[green]running[/green]" if _jobs.is_worker_running() else "[dim]idle[/dim]"
    console.print(f"\n[bold]Sarathi — Background Jobs[/bold]   worker: {worker_status}\n")

    if queue:
        t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        t.add_column("QUEUE", style="cyan", no_wrap=True)
        t.add_column("Project")
        t.add_column("Status")
        t.add_column("Queued at")
        for j in queue:
            name = Path(j.get("project", "?")).name
            t.add_row(j["id"][-12:], name, j.get("status", "?"),
                      j.get("queued_at", "")[:16].replace("T", " "))
        console.print(t)
        console.print()

    if recent:
        t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        t.add_column("ID", style="dim", no_wrap=True)
        t.add_column("Project")
        t.add_column("Status")
        t.add_column("Started")
        for j in reversed(recent[-15:]):
            name = Path(j.get("project", "?")).name
            status = j.get("status", "?")
            color = "green" if status == "done" else "red" if status in ("failed","interrupted") else "yellow"
            ts = j.get("started", j.get("queued_at", ""))[:16].replace("T", " ")
            t.add_row(j["id"][-16:], name, f"[{color}]{status}[/{color}]", ts)
        console.print(t)

    if not queue and not recent:
        console.print("[dim]No jobs yet. Run sarathi viraam to queue generation.[/dim]")

    console.print()
    console.print("[dim]sarathi logs <job-id>   — tail job log[/dim]")
    console.print("[dim]sarathi kill <job-id>   — stop a job[/dim]")
    console.print("[dim]sarathi kill --worker   — stop the queue worker[/dim]")


cli.add_command(jobs_cmd)


# ── ls / suchi ────────────────────────────────────────────────────────────────

@click.command("ls")
def ls_cmd():
    """List all tracked projects with their current status."""
    registry = ptf._load_registry()
    if not registry:
        console.print("[dim]No projects tracked yet. Run [bold]sarathi init[/bold] or [bold]sarathi join[/bold].[/dim]")
        return

    t = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    t.add_column("Name", style="bold")
    t.add_column("Domain", style="dim")
    t.add_column("Status")
    t.add_column("Last gen")
    t.add_column("Slides", justify="right")
    t.add_column("Pending", justify="right")
    t.add_column("Path", style="dim")

    for info in registry.values():
        p = Path(info["path"])
        if not p.exists():
            t.add_row(info.get("name", p.name), "—", "[dim]missing[/dim]", "—", "—", "—", str(p))
            continue
        try:
            s = ptf._project_summary(p)
        except Exception:
            t.add_row(info.get("name", p.name), "—", "[red]error[/red]", "—", "—", "—", str(p))
            continue
        if not s:
            continue
        status = s.get("status", "active")
        clr = {"active": "green", "planning": "blue", "paused": "yellow", "shipped": "cyan"}.get(status, "white")
        pending = len(s.get("pending_files", []))
        t.add_row(
            s.get("name", p.name),
            s.get("domain", "auto"),
            f"[{clr}]{status}[/{clr}]",
            s.get("last_generated", "never"),
            str(s.get("slide_count") or "—"),
            f"[yellow]{pending}[/yellow]" if pending else "—",
            str(p),
        )

    console.print(f"\n[bold]Sarathi — Projects[/bold]   {len(registry)} tracked\n")
    console.print(t)
    console.print()


cli.add_command(ls_cmd)


@click.command("suchi", hidden=True)
def suchi_cmd():
    """List all tracked projects. (suchi = list/index)"""
    ls_cmd.callback()


cli.add_command(suchi_cmd)


# ── remove ────────────────────────────────────────────────────────────────────

@click.command("remove")
@click.argument("folder", type=str)
@click.option("--delete-files", is_flag=True, help="Also delete the project folder from disk.")
def remove_cmd(folder, delete_files):
    """Unregister a project from Sarathi (does not delete files by default)."""
    import shutil as _shutil
    from rich.prompt import Confirm
    folder = _resolve_folder(folder)
    p = Path(folder)
    registry = ptf._load_registry()
    key = str(p)
    name = registry.get(key, {}).get("name", p.name)

    if delete_files:
        if not Confirm.ask(f"  [red]Delete all files in '{name}' at {p}?[/red]", default=False):
            console.print("[dim]Aborted.[/dim]")
            return

    del registry[key]
    ptf._save_registry(registry)
    console.print(f"[green]✓[/green] Unregistered [bold]{name}[/bold] from Sarathi.")

    if delete_files:
        if p.exists():
            _shutil.rmtree(p)
            console.print(f"[green]✓[/green] Deleted folder [dim]{p}[/dim].")
        else:
            console.print(f"[dim]Folder {p} not found on disk.[/dim]")
    else:
        console.print(f"[dim]Files at {p} were not touched. Use --delete-files to remove them.[/dim]")


cli.add_command(remove_cmd)


# ── logs ──────────────────────────────────────────────────────────────────────

@click.command("logs")
@click.argument("job_ref")
@click.option("--lines", default=50, help="Number of log lines to show.")
def logs_cmd(job_ref, lines):
    """Tail the log for a background job — accepts job ID or project name."""
    j = _jobs.resolve_job(job_ref)
    label = j["id"] if j else job_ref
    text = _jobs.tail_log(job_ref, lines=lines)
    console.print(f"[dim]── log: {label} ──[/dim]")
    console.print(text)


cli.add_command(logs_cmd)


@click.command("kill")
@click.argument("job_id", required=False, default=None)
@click.option("--worker", is_flag=True, help="Stop the queue worker process.")
@click.option("--all", "kill_all", is_flag=True, help="Stop all running jobs and the worker.")
def kill_cmd(job_id, worker, kill_all):
    """Stop a background job, the queue worker, or everything."""
    if kill_all:
        stopped = _jobs.kill_worker()
        console.print(f"[yellow]Worker {'stopped' if stopped else 'was not running'}.[/yellow]")
        for j in _jobs.get_all_jobs():
            if j.get("status") == "running":
                _jobs.kill_job(j["id"])
                console.print(f"[yellow]Stopped job {j['id'][-12:]}[/yellow]")
        return
    if worker:
        stopped = _jobs.kill_worker()
        console.print(f"[yellow]Worker {'stopped' if stopped else 'was not running'}.[/yellow]")
        return
    if job_id:
        j = _jobs.resolve_job(job_id)
        real_id = j["id"] if j else job_id
        ok = _jobs.kill_job(real_id)
        console.print(f"[yellow]Job {real_id}: {'stopped' if ok else 'not found or not running'}.[/yellow]")
        return
    console.print("[yellow]Specify a job ID, --worker, or --all.[/yellow]")


cli.add_command(kill_cmd)
