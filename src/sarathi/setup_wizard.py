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
    ("qwen3:1.7b",        "Qwen 3 1.7B (fast)",    2,   False,
     "Tiny & fast on CPU — use with --fast flag (~5 min/presentation)"),
    ("qwen2.5:3b",        "Qwen 2.5 3B (fast)",    3,   False,
     "Good quality/speed balance on CPU — recommended for local-only"),
    ("qwen3.5",           "Qwen 3.5 8B",           6,   False,
     "Best local 8B quality — slow on CPU (~30+ min/presentation)"),
    ("gemma3:12b",        "Gemma 3 12B",           9,   True,
     "Multimodal, 128K context — great for image-heavy projects"),
    ("llama3.2-vision",   "Llama 3.2 Vision 11B",  8,   True,
     "Best local vision model for reading charts/images"),
    ("qwen2.5-coder:7b",  "Qwen 2.5 Coder 7B",     5,  False,
     "Reliable HTML/code generation on CPU"),
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


def _install_ollama(os_name: str) -> None:
    console.print("  [dim]Installing Ollama...[/dim]")
    if os_name == "Linux":
        result = subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True,
        )
        if result.returncode == 0:
            console.print("  [green]✓ Ollama installed.[/green]")
        else:
            console.print("  [red]✗ Install failed.[/red] Try manually:")
            console.print("    [cyan]curl -fsSL https://ollama.com/install.sh | sh[/cyan]")
    elif os_name == "Darwin":
        if shutil.which("brew"):
            result = subprocess.run(["brew", "install", "ollama"])
            if result.returncode == 0:
                console.print("  [green]✓ Ollama installed via Homebrew.[/green]")
            else:
                console.print("  [red]✗ brew install failed.[/red]")
        else:
            console.print(
                "  [yellow]Homebrew not found.[/yellow] "
                "Download from: [cyan]https://ollama.com/download[/cyan]"
            )
    else:
        console.print(
            "  [yellow]Auto-install not supported on Windows.[/yellow]\n"
            "  Download from: [cyan]https://ollama.com/download[/cyan]"
        )


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

    # ── Ollama install + start ─────────────────────────────────────────────────
    console.print("[bold]Checking Ollama...[/bold]")
    installed, running, ollama_bin = check_ollama()

    if not installed:
        console.print("  [yellow]Ollama not found.[/yellow]")
        if Confirm.ask("  Install Ollama now?", default=True):
            _install_ollama(hw["os"])
            # Re-check after install
            installed, running, ollama_bin = check_ollama()
            if not installed:
                console.print(
                    "\n  [red]Could not find ollama after install.[/red]\n"
                    "  Open a new terminal and re-run [bold]sarathi setup[/bold].\n"
                )
        else:
            console.print(
                f"  Skipping. Install manually: [cyan]{ollama_install_hint(hw['os'])}[/cyan]\n"
            )

    if installed and not running:
        console.print(f"  [yellow]Ollama installed but not running.[/yellow]")
        if Confirm.ask("  Start ollama serve now (background)?", default=True):
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            import time; time.sleep(2)
            _, running, _ = check_ollama()

    if installed and running:
        console.print(f"  [green]✓ Ollama running.[/green]")
    console.print()

    # ── Model selection ────────────────────────────────────────────────────────
    recommended, others = recommend_models(hw)

    # Detect already-pulled models — check disk first, fall back to ollama list
    already_pulled: set[str] = set()

    # Primary: scan ~/.ollama/models/manifests/ — works even if server is down
    # Structure: manifests/<registry>/<namespace>/<model>/<tag>  (tag is a file)
    manifests_dir = Path.home() / ".ollama" / "models" / "manifests"
    if manifests_dir.exists():
        for manifest_file in manifests_dir.rglob("*"):
            if manifest_file.is_file():
                # model name is the parent dir of the tag file
                already_pulled.add(manifest_file.parent.name.lower())

    # Fallback: ollama list (requires server running)
    if not already_pulled and installed and running:
        try:
            raw = subprocess.run(
                [ollama_bin, "list"], capture_output=True, text=True, timeout=5
            ).stdout
            for line in raw.splitlines()[1:]:
                parts = line.split()
                if parts:
                    already_pulled.add(parts[0].split(":")[0].lower())
        except Exception:
            pass

    console.print("[bold]Available models for your hardware:[/bold]")
    model_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2),
                        header_style="bold cyan")
    model_table.add_column("#",      width=3,  style="dim")
    model_table.add_column("Model",  style="bold")
    model_table.add_column("RAM",    width=8)
    model_table.add_column("Vision", width=7)
    model_table.add_column("Status", width=10)
    model_table.add_column("Notes",  style="dim")

    for i, (name, display, needed, vision, note) in enumerate(recommended, 1):
        is_cloud  = ":cloud" in name
        base_name = name.split(":")[0]
        pulled    = base_name in already_pulled or is_cloud
        ram_str   = "[green]cloud[/green]" if is_cloud else f"{needed} GB"
        vis_str   = "[cyan]✓[/cyan]" if vision else "[dim]—[/dim]"
        status    = "[green]ready[/green]" if pulled else "[dim]not pulled[/dim]"
        model_table.add_row(str(i), display, ram_str, vis_str, status, note)

    console.print(model_table)
    if others:
        console.print(f"[dim]  {len(others)} model(s) need more RAM.[/dim]")
    console.print()

    # ── Role assignment ────────────────────────────────────────────────────────
    console.print(Panel(
        "[bold]Sarathi uses three specialized model roles:[/bold]\n\n"
        "  [cyan]Planner[/cyan]   — narrative outline, reasoning  "
        "[dim](recommended: gemma3:4b)[/dim]\n"
        "  [cyan]Coder[/cyan]     — HTML/JS slide rendering        "
        "[dim](recommended: qwen2.5-coder:3b)[/dim]\n"
        "  [cyan]Vision[/cyan]    — image/chart interpretation     "
        "[dim](recommended: gemma3:4b — multimodal)[/dim]\n\n"
        "[dim]Enter a number from the table above or type a model name directly.[/dim]",
        border_style="cyan", title="Model Roles"
    ))

    def _pick_model(role: str, default_name: str, default_display: str) -> str:
        """Interactively pick and optionally pull a model for a role."""
        choice = console.input(
            f"  [bold]{role}[/bold] model "
            f"[dim](Enter for [cyan]{default_name}[/cyan])[/dim]: "
        ).strip()

        if not choice:
            name = default_name
        elif choice.isdigit():
            idx = int(choice) - 1
            name = recommended[idx][0] if 0 <= idx < len(recommended) else default_name
        else:
            name = choice  # typed directly

        base = name.split(":")[0]
        is_ready = base in already_pulled or ":cloud" in name
        bin_ = ollama_bin or _ollama_bin()

        if is_ready:
            console.print(f"    [green]✓ {name} already ready.[/green]")
        elif bin_:
            if Confirm.ask(f"    Pull [bold]{name}[/bold] now?", default=True):
                subprocess.run([bin_, "pull", name])
        else:
            console.print(f"    [yellow]Run: ollama pull {name}[/yellow]")

        return name

    planner_model = _pick_model("Planner", "gemma3:4b",       "Gemma 3 4B")
    coder_model   = _pick_model("Coder",   "qwen2.5-coder:3b","Qwen 2.5 Coder 3B")
    vision_model  = _pick_model("Vision",  "gemma3:4b",       "Gemma 3 4B")

    primary_model = coder_model  # used as fallback `model` key

    # ── Vision model check ────────────────────────────────────────────────────
    _VISION_KEYWORDS = {"vision", "vl", "llava", "minicpm", "gemma3"}
    has_vision = any(
        any(kw in m.lower() for kw in _VISION_KEYWORDS)
        for m in already_pulled
    )

    if not has_vision:
        console.print()
        console.print(
            "[yellow]⚠ No vision model detected.[/yellow] "
            "Sarathi uses a vision model to read charts and images in your projects.\n"
            "  [dim]Recommended: [bold]gemma3:12b[/bold] (multimodal) or "
            "[bold]llama3.2-vision[/bold][/dim]"
        )
        bin_ = ollama_bin or _ollama_bin()
        if bin_ and Confirm.ask("  Pull gemma3:12b (vision) now?", default=True):
            subprocess.run([bin_, "pull", "gemma3:12b"])
            already_pulled.add("gemma3")
            console.print("  [green]✓ gemma3:12b ready — vision support enabled.[/green]")
    else:
        vision_models = [m for m in already_pulled
                         if any(kw in m.lower() for kw in _VISION_KEYWORDS)]
        console.print(
            f"  [green]✓ Vision model available:[/green] "
            f"[bold]{', '.join(vision_models)}[/bold]"
        )
    console.print()

    # ── Save model roles to global config ────────────────────────────────────
    import json
    global_cfg_dir = Path.home() / ".config" / "sarathi"
    global_cfg_dir.mkdir(parents=True, exist_ok=True)
    global_cfg = global_cfg_dir / "config.json"
    existing = {}
    if global_cfg.exists():
        try:
            existing = json.loads(global_cfg.read_text())
        except Exception:
            pass
    existing.update({
        "model":         primary_model,
        "planner_model": planner_model,
        "coder_model":   coder_model,
        "vision_model":  vision_model,
    })
    global_cfg.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    console.print(
        f"\n[green]✓ Model roles saved to ~/.config/sarathi/config.json[/green]\n"
        f"  Planner : [cyan]{planner_model}[/cyan]\n"
        f"  Coder   : [cyan]{coder_model}[/cyan]\n"
        f"  Vision  : [cyan]{vision_model}[/cyan]"
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
