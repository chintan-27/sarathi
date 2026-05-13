from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm
from rich import box

console = Console()

# ── Model catalogue ────────────────────────────────────────────────────────────
# Each entry: (ollama_name, display_name, ram_gb_needed, vision, quality_note)
MODELS = [
    ("kimi-k2.5:cloud",   "Kimi K2.5 Cloud",      2,   False,
     "Best overall — cloud-routed via Ollama, no local RAM needed"),
    ("qwen3.5:cloud",     "Qwen 3.5 Cloud",        2,   False,
     "Fast cloud model, great structured output"),
    ("glm-5:cloud",       "GLM-5 Cloud",           2,   False,
     "Strong reasoning, good for data analysis decks"),
    ("qwen3.5",           "Qwen 3.5 (local 8B)",   6,   False,
     "Best local 8B — fast HTML generation"),
    ("gemma3:12b",        "Gemma 3 12B",           9,   True,
     "Multimodal, 128K context — great for image-heavy projects"),
    ("llama3.2-vision",   "Llama 3.2 Vision 11B",  8,   True,
     "Best local vision model for reading charts/images"),
    ("phi4",              "Phi-4 14B",             10,  False,
     "Strong reasoning — good for ML experiment decks"),
    ("qwen2.5-coder:7b",  "Qwen 2.5 Coder 7B",     5,  False,
     "Reliable HTML/code generation, very fast on CPU"),
]


# ── Hardware detection ─────────────────────────────────────────────────────────

def detect_hardware() -> dict:
    import psutil

    ram_total = psutil.virtual_memory().total
    ram_avail = psutil.virtual_memory().available
    cpu_name  = _cpu_name()
    cpu_cores = psutil.cpu_count(logical=False) or 1
    gpu_name, vram_gb = _detect_gpu()

    return {
        "ram_total_gb": ram_total / 1e9,
        "ram_avail_gb": ram_avail / 1e9,
        "cpu_name":     cpu_name,
        "cpu_cores":    cpu_cores,
        "gpu_name":     gpu_name,
        "vram_gb":      vram_gb,
        "os":           platform.system(),
    }


def _cpu_name() -> str:
    try:
        if platform.system() == "Linux":
            out = Path("/proc/cpuinfo").read_text()
            for line in out.splitlines():
                if "model name" in line:
                    return line.split(":", 1)[1].strip()
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True
            )
            return result.stdout.strip()
        elif platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True, text=True
            )
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            return lines[1] if len(lines) > 1 else "Unknown"
    except Exception:
        pass
    return "Unknown CPU"


def _detect_gpu() -> tuple[str, float]:
    # Try nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().splitlines()[0]
            parts = line.split(",")
            name = parts[0].strip()
            vram = float(parts[1].strip()) / 1024 if len(parts) > 1 else 0.0
            return name, round(vram, 1)
    except Exception:
        pass

    # Try rocm-smi (AMD)
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return "AMD GPU (ROCm)", 0.0
    except Exception:
        pass

    return "None detected", 0.0


# ── Ollama detection ───────────────────────────────────────────────────────────

_OLLAMA_PATHS = [
    "ollama",                          # already in PATH
    "/usr/local/bin/ollama",           # default Linux install
    "/usr/bin/ollama",
    str(Path.home() / ".local/bin/ollama"),
    "/opt/homebrew/bin/ollama",        # macOS Homebrew (Apple Silicon)
    "/usr/local/opt/ollama/bin/ollama",# macOS Homebrew (Intel)
]


def _ollama_bin() -> str | None:
    """Return the first usable ollama binary path, or None."""
    for p in _OLLAMA_PATHS:
        if shutil.which(p) or Path(p).is_file():
            return p
    return None


def check_ollama() -> tuple[bool, bool, str | None]:
    """Returns (is_installed, is_running, binary_path)."""
    bin_path = _ollama_bin()
    if not bin_path:
        return False, False, None
    try:
        result = subprocess.run(
            [bin_path, "list"], capture_output=True, text=True, timeout=5
        )
        return True, result.returncode == 0, bin_path
    except Exception:
        return True, False, bin_path


def ollama_install_hint(os_name: str) -> str:
    if os_name == "Darwin":
        return "brew install ollama  or  https://ollama.com/download"
    elif os_name == "Windows":
        return "https://ollama.com/download  (Windows installer)"
    else:
        return "curl -fsSL https://ollama.com/install.sh | sh"


# ── Model recommendation ───────────────────────────────────────────────────────

def recommend_models(hw: dict) -> list[tuple]:
    ram = hw["ram_avail_gb"]
    vram = hw["vram_gb"]
    recommended = []
    others = []

    for m in MODELS:
        name, display, needed, vision, note = m
        is_cloud = ":cloud" in name
        fits = is_cloud or (ram >= needed + 1.5)  # keep 1.5 GB headroom

        if is_cloud or fits:
            recommended.append(m)
        else:
            others.append(m)

    return recommended, others


# ── Playwright check ───────────────────────────────────────────────────────────

def check_playwright() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=10
        )
        # If chromium is already installed, dry-run exits 0 with no output
        return "chromium" not in (result.stdout + result.stderr).lower() or result.returncode == 0
    except Exception:
        return False


# ── Main wizard ────────────────────────────────────────────────────────────────

def run() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Sarathi Setup[/bold cyan]\n"
        "[dim]Let's get your environment ready.[/dim]",
        border_style="cyan",
    ))
    console.print()

    # ── Hardware report ────────────────────────────────────────────────────────
    console.print("[bold]Detecting your hardware...[/bold]")
    hw = detect_hardware()

    hw_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    hw_table.add_column(style="dim")
    hw_table.add_column(style="bold")
    hw_table.add_row("CPU",      hw["cpu_name"])
    hw_table.add_row("Cores",    str(hw["cpu_cores"]))
    hw_table.add_row("RAM",      f"{hw['ram_total_gb']:.1f} GB total  ·  "
                                  f"[green]{hw['ram_avail_gb']:.1f} GB available[/green]")
    hw_table.add_row("GPU",      hw["gpu_name"])
    hw_table.add_row("VRAM",     f"{hw['vram_gb']:.1f} GB" if hw["vram_gb"] else "[dim]—[/dim]")
    hw_table.add_row("OS",       hw["os"])
    console.print(hw_table)

    if hw["vram_gb"] < 4 and hw["vram_gb"] > 0:
        console.print("[yellow]  ⚠ GPU VRAM is low — Sarathi will run models on CPU via Ollama.[/yellow]")
    elif hw["vram_gb"] == 0:
        console.print("[dim]  Running CPU-only. Cloud models via Ollama are recommended.[/dim]")
    console.print()

    # ── Ollama check ───────────────────────────────────────────────────────────
    console.print("[bold]Checking Ollama...[/bold]")
    installed, running, ollama_bin = check_ollama()

    if not installed:
        console.print(f"[red]  ✗ Ollama not found.[/red]")
        console.print(f"  Install it: [cyan]{ollama_install_hint(hw['os'])}[/cyan]")
        console.print(
            "  Then open a [bold]new terminal[/bold] and re-run [bold]sarathi setup[/bold]."
        )
        console.print()
    elif not running:
        console.print(f"[yellow]  ⚠ Ollama found at {ollama_bin} but not running.[/yellow]")
        console.print(f"  Start it:  [cyan]{ollama_bin} serve[/cyan]  (in a separate terminal)")
        console.print()
    else:
        console.print(f"  [green]✓ Ollama running[/green] [dim]({ollama_bin})[/dim]")
        console.print()

    # ── Model selection ────────────────────────────────────────────────────────
    recommended, others = recommend_models(hw)

    console.print("[bold]Recommended models for your hardware:[/bold]")
    model_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2),
                        header_style="bold cyan")
    model_table.add_column("#",     width=3, style="dim")
    model_table.add_column("Model", style="bold")
    model_table.add_column("RAM",   width=8)
    model_table.add_column("Vision", width=7)
    model_table.add_column("Notes", style="dim")

    for i, (name, display, needed, vision, note) in enumerate(recommended, 1):
        is_cloud = ":cloud" in name
        ram_str = "[green]cloud[/green]" if is_cloud else f"{needed} GB"
        vis_str = "[cyan]✓[/cyan]" if vision else "[dim]—[/dim]"
        model_table.add_row(str(i), display, ram_str, vis_str, note)

    console.print(model_table)

    if others:
        console.print(
            f"[dim]  {len(others)} model(s) skipped — need more RAM than available.[/dim]"
        )
    console.print()

    # Ask which to pull
    default_choice = "1"
    choice_str = console.input(
        f"[bold]Pick model(s) to pull[/bold] (comma-separated numbers, or press Enter for [cyan]#1[/cyan]): "
    ).strip() or default_choice

    chosen_indices = []
    for part in choice_str.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(recommended):
                chosen_indices.append(idx)
        except ValueError:
            pass

    if not chosen_indices:
        console.print("[yellow]No valid selection — skipping model pull.[/yellow]")
        chosen_models = []
    else:
        chosen_models = [recommended[i] for i in chosen_indices]

    # Pull each chosen model
    primary_model = None
    for name, display, needed, vision, note in chosen_models:
        console.print(f"\n[dim]Pulling [bold]{display}[/bold] ([cyan]{name}[/cyan])...[/dim]")
        is_cloud = ":cloud" in name
        if is_cloud:
            console.print(
                "  [dim]Cloud model — no download needed, routed via Ollama at runtime.[/dim]"
            )
        else:
            bin_ = ollama_bin or _ollama_bin()
            if not bin_:
                console.print(
                    "  [red]✗ ollama not in PATH.[/red] "
                    "Open a new terminal and run [cyan]sarathi setup[/cyan] again, "
                    "or pull manually: [cyan]ollama pull " + name + "[/cyan]"
                )
            else:
                try:
                    result = subprocess.run([bin_, "pull", name])
                    if result.returncode == 0:
                        console.print(f"  [green]✓ {display} ready.[/green]")
                    else:
                        console.print(f"  [red]✗ Pull failed for {name}.[/red]")
                except FileNotFoundError:
                    console.print(
                        f"  [red]✗ Could not run {bin_}.[/red] "
                        f"Try: [cyan]ollama pull {name}[/cyan] in a new terminal."
                    )

        if primary_model is None:
            primary_model = name

    # ── Save primary model to global config ────────────────────────────────────
    if primary_model:
        from . import config as cfg
        global_cfg_dir = Path.home() / ".config" / "sarathi"
        global_cfg_dir.mkdir(parents=True, exist_ok=True)
        global_cfg = global_cfg_dir / "config.json"
        import json
        existing = {}
        if global_cfg.exists():
            try:
                existing = json.loads(global_cfg.read_text())
            except Exception:
                pass
        existing["model"] = primary_model
        global_cfg.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        console.print(
            f"\n[green]✓ Default model set to [bold]{primary_model}[/bold] "
            f"(saved to ~/.config/sarathi/config.json)[/green]"
        )

    # ── How Sarathi uses Ollama ────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold cyan]How Sarathi uses Ollama[/bold cyan]\n\n"
        "Sarathi calls the Anthropic Python SDK pointed at Ollama's\n"
        "Anthropic-compatible API at [bold]http://localhost:11434[/bold].\n"
        "No Anthropic account or API key needed — everything runs locally.\n\n"
        "[bold]Just make sure Ollama is running and your model is pulled:[/bold]\n"
        "  [cyan]ollama serve[/cyan]\n"
        "  [cyan]ollama pull qwen3.5[/cyan]\n"
        "  [cyan]sarathi track myproject/[/cyan]\n\n"
        "[dim]Sarathi auto-configures the API endpoint — no env vars needed.[/dim]",
        border_style="cyan",
    ))

    # ── Playwright ─────────────────────────────────────────────────────────────
    console.print()
    console.print("[bold]Checking Playwright (PDF export)...[/bold]")
    if Confirm.ask("  Install/verify Playwright Chromium?", default=True):
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=False
        )
        if result.returncode == 0:
            console.print("  [green]✓ Chromium ready.[/green]")
        else:
            console.print("  [yellow]⚠ Playwright install had issues — PDF export may not work.[/yellow]")

    # ── Done ───────────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold green]✓ Sarathi is ready![/bold green]\n\n"
        "Get started:\n"
        "  [cyan]sarathi arambh \"my-project\" \"what this project is about\"[/cyan]\n"
        "  [cyan]sarathi portfolio[/cyan]  →  dashboard at localhost:7432\n\n"
        "[dim]Run [bold]sarathi --help[/bold] to see all commands.[/dim]",
        border_style="green",
    ))
