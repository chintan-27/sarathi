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


# ── Shared benchmark function ─────────────────────────────────────────────────

def _unload_all() -> None:
    """Unload every model currently loaded in Ollama RAM before benchmarking."""
    import ollama as _ollama
    try:
        running = _ollama.ps()
        for m in getattr(running, "models", []):
            try:
                model_name = getattr(m, "model", None) or getattr(m, "name", None)
                if model_name:
                    _ollama.generate(model=model_name, prompt="", keep_alive=0)
            except Exception:
                pass
    except Exception:
        pass


def benchmark_model(name: str, verbose: bool = False) -> dict:
    """Unload all models, then cold-start benchmark the given model.

    Reports:
      - load_s:      time to load model into RAM (cold start)
      - tps:         pure generation speed after load (tok/s)
      - eval_tokens: number of tokens generated
    """
    import ollama as _ollama
    from rich.rule import Rule

    _PROMPT = "Write the numbers 1 through 50, one per line. Only numbers."

    try:
        console.print(f"[dim]  Unloading models from RAM...[/dim]", end="\r")
        _unload_all()

        if verbose:
            console.print()
            console.print(Rule(f"[bold cyan]{name}[/bold cyan]", style="cyan"))
            console.print(f"[dim]PROMPT:[/dim]  {_PROMPT}")
            console.print(f"[dim]Sending to Ollama...[/dim]")

        resp = _ollama.generate(
            model=name,
            prompt=_PROMPT,
            options={"num_predict": 100},
            keep_alive=0,
        )

        eval_count    = resp.get("eval_count", 0)
        eval_duration = resp.get("eval_duration", 0)   # ns
        load_duration = resp.get("load_duration", 0)   # ns
        prompt_eval   = resp.get("prompt_eval_count", 0)
        prompt_dur    = resp.get("prompt_eval_duration", 0)
        total_ns      = resp.get("total_duration", 0)
        response_text = resp.get("response", "")

        if eval_count and eval_duration:
            tps = eval_count / (eval_duration / 1e9)
        else:
            tps = len(response_text.split()) / max(total_ns / 1e9, 0.001)

        if verbose:
            console.print(f"\n[dim]RESPONSE:[/dim]")
            console.print(f"[green]{response_text.strip()}[/green]")
            console.print()
            console.print(f"[dim]  Load time      :[/dim] {load_duration/1e9:.2f}s")
            console.print(f"[dim]  Prompt tokens  :[/dim] {prompt_eval}  ({prompt_dur/1e9:.2f}s)")
            console.print(f"[dim]  Gen tokens     :[/dim] {eval_count}  ({eval_duration/1e9:.2f}s)")
            console.print(f"[dim]  Gen speed      :[/dim] [bold]{tps:.1f} tok/s[/bold]")
            console.print(f"[dim]  Total          :[/dim] {total_ns/1e9:.2f}s")
            console.print()

        return {
            "tps":         tps,
            "latency":     total_ns / 1e9,
            "load_s":      load_duration / 1e9,
            "eval_tokens": eval_count,
            "response":    response_text,
            "ok":          True,
        }
    except Exception as e:
        if verbose:
            console.print(f"[red]  Error: {e}[/red]")
        return {"tps": 0, "latency": 0, "ok": False, "error": str(e)}

# ── Model catalogue ────────────────────────────────────────────────────────────
# Each entry: (ollama_name, display_name, ram_gb_needed, vision, quality_note)
MODELS = [
    # ── Cloud (no local RAM) ──────────────────────────────────────────────────
    ("kimi-k2.5:cloud",      "Kimi K2.5 Cloud",         2,  False,
     "Best overall quality — cloud-routed, no local RAM needed"),
    ("qwen3.5:cloud",        "Qwen 3.5 Cloud",          2,  False,
     "Fast cloud, great structured output"),
    ("glm-5:cloud",          "GLM-5 Cloud",             2,  False,
     "Strong reasoning, good for data analysis decks"),

    # ── Tiny / fast (≤ 2 GB) — ideal for --fast mode ─────────────────────────
    ("qwen3:1.7b",           "Qwen 3 1.7B",             2,  False,
     "Fastest local model — best for --fast mode"),
    ("qwen2.5:1.5b",         "Qwen 2.5 1.5B",           2,  False,
     "Very small, fast on any CPU"),
    ("gemma3:1b",            "Gemma 3 1B",              2,  False,
     "Tiny Gemma — fast, decent quality"),

    # ── Small (2–4 GB) — good speed/quality balance ───────────────────────────
    ("qwen2.5:3b",           "Qwen 2.5 3B",             3,  False,
     "Best small general model — recommended fast model"),
    ("qwen2.5-coder:3b",     "Qwen 2.5 Coder 3B",       3,  False,
     "Small coder — recommended for --fast HTML generation"),
    ("gemma3:4b",            "Gemma 3 4B",              4,  True,
     "Multimodal, good reasoning — recommended planner + vision"),
    ("phi4-mini",            "Phi-4 Mini",              4,  False,
     "Strong reasoning for a small model"),

    # ── Medium (4–8 GB) — quality coder/planner models ───────────────────────
    ("qwen2.5-coder:7b",     "Qwen 2.5 Coder 7B",       5,  False,
     "Recommended coder — strong HTML/JS output"),
    ("qwen2.5:7b",           "Qwen 2.5 7B",             5,  False,
     "Good all-rounder, solid reasoning"),
    ("qwen3.5",              "Qwen 3.5 8B",             6,  False,
     "Best local 8B quality"),
    ("mistral:7b",           "Mistral 7B",              5,  False,
     "Fast and capable general model"),
    ("llama3.1:8b",          "Llama 3.1 8B",            6,  False,
     "Meta's capable 8B model"),
    ("deepseek-coder-v2:16b","DeepSeek Coder V2 16B",   10, False,
     "Elite coding model — best HTML/JS if RAM allows"),

    # ── Large vision (8–12 GB) ────────────────────────────────────────────────
    ("llama3.2-vision",      "Llama 3.2 Vision 11B",    8,  True,
     "Best vision model for reading charts and images"),
    ("gemma3:12b",           "Gemma 3 12B",             9,  True,
     "Multimodal, 128K context, great for image-heavy projects"),
    ("llava:13b",            "LLaVA 13B",               9,  True,
     "Strong vision-language model"),
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


# ── Cloud API setup ────────────────────────────────────────────────────────────

# ── Cloud role suggestion ──────────────────────────────────────────────────────

_ROLE_KEYWORDS: dict[str, list[str]] = {
    "planner": ["70b", "120b", "large", "llama-3.3", "llama-3.1-70", "gemma-3-27",
                "gpt-4", "claude-3", "nemotron-3-super", "mistral-large"],
    "coder":   ["coder", "codestral", "code", "deepseek-coder", "qwen-coder",
                "qwen2.5-coder", "gpt-oss"],
    "vision":  ["vision", "vl", "gemma-3", "gpt-4o", "claude-3", "llava", "minicpm"],
    "fast":    ["8b", "7b", "3b", "mini", "small", "nano", "mistral-7b",
                "granite-3.3-8b", "llama-3.1-8b"],
}
_IMG_KEYWORDS = ["flux", "dall-e", "stable-diffusion", "imagen", "playground"]
_SKIP_KEYWORDS = ["embed", "whisper", "kokoro", "tts", "asr"]


def _suggest_cloud_roles(model_ids: list[str]) -> dict:
    """Auto-score models and suggest the best for each agent role."""
    skip = lambda m: any(k in m.lower() for k in _SKIP_KEYWORDS)
    img  = lambda m: any(k in m.lower() for k in _IMG_KEYWORDS)

    llm_models = [m for m in model_ids if not skip(m) and not img(m)]
    img_models  = [m for m in model_ids if img(m)]

    if not llm_models:
        return {}

    def _score(model_id: str, keywords: list[str]) -> int:
        s = model_id.lower()
        return sum(10 for k in keywords if k in s)

    suggestions: dict[str, str] = {}
    for role, kws in _ROLE_KEYWORDS.items():
        scored = sorted(llm_models, key=lambda m: _score(m, kws), reverse=True)
        suggestions[role] = scored[0]

    suggestions["image_gen"] = img_models[0] if img_models else ""
    return suggestions


# ── Cloud setup flow ───────────────────────────────────────────────────────────

def _run_cloud_setup() -> "dict | None":
    """Interactive cloud API setup. Returns config dict (decrypted key) or None."""
    console.print()
    url = console.input(
        "  [bold]API URL[/bold]  [dim]e.g. https://api.ai.it.ufl.edu  (Enter to skip)[/dim]: "
    ).strip()
    if not url:
        return None

    key = console.input("  [bold]API Key[/bold]: ").strip()
    if not key:
        console.print("  [yellow]No key entered.[/yellow]\n")
        return None

    console.print(f"  [dim]Connecting to {url}...[/dim]", end="\r")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url=url)
        models_resp = client.models.list()
        model_ids = [m.id for m in (models_resp.data or [])]
    except Exception as exc:
        console.print(f"  [red]✗ Connection failed: {exc}[/red]")
        return None

    if not model_ids:
        console.print("  [yellow]⚠ Connected but no models listed.[/yellow]")
        return None

    console.print(f"  [green]✓ Connected — {len(model_ids)} model(s) available[/green]   ")
    console.print()

    # Categorise and show full model list
    skip = lambda m: any(k in m.lower() for k in _SKIP_KEYWORDS)
    img  = lambda m: any(k in m.lower() for k in _IMG_KEYWORDS)
    llm_models = [m for m in model_ids if not skip(m) and not img(m)]
    img_models  = [m for m in model_ids if img(m)]
    other_models = [m for m in model_ids if skip(m)]

    model_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2),
                        header_style="bold cyan")
    model_table.add_column("#", width=4, style="dim")
    model_table.add_column("Model ID", style="bold")
    model_table.add_column("Type", width=12)

    for i, mid in enumerate(model_ids, 1):
        mtype = (
            "[cyan]image gen[/cyan]" if img(mid)
            else "[dim]embed/audio[/dim]" if skip(mid)
            else "[green]LLM[/green]"
        )
        model_table.add_row(str(i), mid, mtype)

    console.print(model_table)
    console.print()

    # Auto-suggest roles
    suggestions = _suggest_cloud_roles(model_ids)
    if not suggestions:
        console.print("  [yellow]Could not determine model roles — please enter manually.[/yellow]")
        suggestions = {}

    # Show suggestion table and let user confirm or override
    sug_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2),
                      header_style="bold cyan", title="Suggested model roles")
    sug_table.add_column("Role", width=12)
    sug_table.add_column("Suggested model", style="bold")
    sug_table.add_column("", style="dim")

    role_labels = {
        "planner":   ("Planner",   "narrative outline, reasoning"),
        "coder":     ("Coder",     "HTML/slide generation"),
        "vision":    ("Vision",    "image/chart interpretation"),
        "fast":      ("Fast",      "--fast mode (optional)"),
        "image_gen": ("Image gen", "AI-generated visuals (optional)"),
    }
    for role, (label, hint) in role_labels.items():
        sug = suggestions.get(role, "—")
        sug_table.add_row(label, sug if sug else "[dim]—[/dim]", hint)
    console.print(sug_table)

    accept = Confirm.ask("  Accept all suggestions?", default=True)

    def _pick_role(role: str, label: str, hint: str) -> str:
        default = suggestions.get(role, model_ids[0] if model_ids else "")
        if accept:
            return default
        choice = console.input(
            f"  [bold]{label}[/bold] [dim]({hint})[/dim] "
            f"[dim]Enter # or model name, default=[cyan]{default}[/cyan][/dim]: "
        ).strip()
        if not choice:
            return default
        if choice.isdigit():
            idx = int(choice) - 1
            return model_ids[idx] if 0 <= idx < len(model_ids) else default
        return choice

    planner   = _pick_role("planner",   "Planner",   "reasoning, outline")
    coder     = _pick_role("coder",     "Coder",     "HTML/code generation")
    vision    = _pick_role("vision",    "Vision",    "image understanding")
    fast_role = _pick_role("fast",      "Fast",      "--fast mode")

    # Image gen: only ask if models are available
    image_gen_model   = ""
    image_gen_enabled = False
    if img_models or suggestions.get("image_gen"):
        img_default = suggestions.get("image_gen", "")
        if Confirm.ask(
            f"  Enable AI image generation for slides? "
            f"[dim](model: {img_default or img_models[0] if img_models else 'n/a'})[/dim]",
            default=bool(img_default or img_models),
        ):
            image_gen_model = img_default or (img_models[0] if img_models else "")
            image_gen_enabled = True

    # Encrypt and save
    from . import keystore as _ks
    from . import config as _cfg
    encrypted_key = _ks.encrypt(key)

    cloud_cfg = {
        "backend":          "cloud",
        "cloud_api_url":    url,
        "cloud_api_key":    encrypted_key,
        "planner_model":    planner,
        "coder_model":      coder,
        "vision_model":     vision,
        "fast_model":       fast_role,
        "model":            coder,
        "image_gen_model":  image_gen_model,
        "image_gen_enabled": image_gen_enabled,
    }
    _cfg.save_global_config(cloud_cfg)

    console.print()
    img_line = (
        f"  Image gen: [cyan]{image_gen_model}[/cyan] ✓\n"
        if image_gen_enabled else
        "  Image gen: [dim]disabled[/dim]\n"
    )
    console.print(
        f"[green]✓ Cloud API configured.[/green]\n"
        f"  Planner  : [cyan]{planner}[/cyan]\n"
        f"  Coder    : [cyan]{coder}[/cyan]\n"
        f"  Vision   : [cyan]{vision}[/cyan]\n"
        f"  Fast     : [cyan]{fast_role}[/cyan]\n"
        + img_line
    )
    return {**cloud_cfg, "cloud_api_key": key}  # decrypted key for tip display


# ── Offline (Ollama) setup flow ────────────────────────────────────────────────

def _run_offline_setup(hw: dict, fallback_prefix: str = "") -> dict:
    """Run Ollama model setup. Returns config dict with model role assignments.

    fallback_prefix: if "fallback_", saves roles as fallback_planner_model etc.
    """
    # Ollama install + start
    console.print("[bold]Checking Ollama...[/bold]")
    installed, running, ollama_bin = check_ollama()

    if not installed:
        console.print("  [yellow]Ollama not found.[/yellow]")
        if Confirm.ask("  Install Ollama now?", default=True):
            _install_ollama(hw["os"])
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
        console.print("[yellow]  Ollama installed but not running.[/yellow]")
        if Confirm.ask("  Start ollama serve now (background)?", default=True):
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            import time; time.sleep(2)
            _, running, _ = check_ollama()

    if installed and running:
        console.print("  [green]✓ Ollama running.[/green]")
    console.print()

    # Detect already-pulled models
    already_pulled: set[str] = set()
    pulled_bases:   set[str] = set()
    pulled_versions: dict[str, list[str]] = {}

    manifests_dir = Path.home() / ".ollama" / "models" / "manifests"
    if manifests_dir.exists():
        for manifest_file in manifests_dir.rglob("*"):
            if manifest_file.is_file():
                model_name = manifest_file.parent.name.lower()
                tag        = manifest_file.name.lower()
                already_pulled.add(f"{model_name}:{tag}")
                pulled_bases.add(model_name)
                pulled_versions.setdefault(model_name, []).append(tag)

    if not already_pulled and installed and running:
        try:
            raw = subprocess.run(
                [ollama_bin, "list"], capture_output=True, text=True, timeout=5
            ).stdout
            for line in raw.splitlines()[1:]:
                parts = line.split()
                if parts:
                    full = parts[0].lower()
                    base = full.split(":")[0]
                    already_pulled.add(full)
                    pulled_bases.add(base)
                    pulled_versions.setdefault(base, []).append(
                        full.split(":")[-1] if ":" in full else "latest"
                    )
        except Exception:
            pass

    # Model catalogue
    recommended, others = recommend_models(hw)

    console.print("[bold]Available models for your hardware:[/bold]")
    model_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2),
                        header_style="bold cyan")
    model_table.add_column("#",      width=3,  style="dim")
    model_table.add_column("Model",  style="bold")
    model_table.add_column("RAM",    width=8)
    model_table.add_column("Vision", width=7)
    model_table.add_column("Status", width=10)
    model_table.add_column("Notes",  style="dim")

    for i, (name, display, needed, vision_cap, note) in enumerate(recommended, 1):
        is_cloud  = ":cloud" in name
        base_name = name.split(":")[0].lower()
        tag       = name.split(":")[-1].lower() if ":" in name else "latest"
        full_low  = f"{base_name}:{tag}"
        if is_cloud:
            status = "[green]cloud[/green]"
        elif full_low in already_pulled:
            status = "[green]ready[/green]"
        elif base_name in pulled_bases:
            avail  = pulled_versions.get(base_name, [])
            status = f"[yellow]{base_name}:{avail[0]}[/yellow]"
        else:
            status = "[dim]not pulled[/dim]"
        ram_str = "[green]cloud[/green]" if is_cloud else f"{needed} GB"
        vis_str = "[cyan]✓[/cyan]" if vision_cap else "[dim]—[/dim]"
        model_table.add_row(str(i), display, ram_str, vis_str, status, note)

    console.print(model_table)
    if others:
        console.print(f"[dim]  {len(others)} model(s) need more RAM.[/dim]")
    console.print()

    # Role assignment
    console.print(Panel(
        "[bold]Sarathi uses specialized model roles:[/bold]\n\n"
        "  [cyan]Planner[/cyan] — narrative outline, reasoning   [dim](gemma3:4b)[/dim]\n"
        "  [cyan]Coder[/cyan]   — HTML/JS slide rendering         [dim](qwen2.5-coder:3b)[/dim]\n"
        "  [cyan]Vision[/cyan]  — image/chart interpretation      [dim](gemma3:4b multimodal)[/dim]\n"
        "  [cyan]Fast[/cyan]    — single-pass --fast mode         [dim](qwen2.5:3b)[/dim]\n\n"
        "[dim]Enter # from the table or a model name directly.[/dim]",
        border_style="cyan", title="Model Roles",
    ))

    def _pick_model(role: str, default_name: str) -> str:
        choice = console.input(
            f"  [bold]{role}[/bold] [dim](Enter for [cyan]{default_name}[/cyan])[/dim]: "
        ).strip()
        if not choice:
            name = default_name
        elif choice.isdigit():
            idx  = int(choice) - 1
            name = recommended[idx][0] if 0 <= idx < len(recommended) else default_name
        else:
            name = choice

        base     = name.split(":")[0].lower()
        tag      = name.split(":")[-1].lower() if ":" in name else "latest"
        full     = f"{base}:{tag}"
        is_cloud = ":cloud" in name
        exact_ok = full in already_pulled or is_cloud
        base_ok  = base in pulled_bases
        bin_     = ollama_bin or _ollama_bin()

        if exact_ok:
            console.print(f"    [green]✓ {name} ready.[/green]")
        elif base_ok:
            avail_tag   = pulled_versions[base][0]
            actual_name = f"{base}:{avail_tag}"
            console.print(
                f"    [yellow]⚠ using [bold]{actual_name}[/bold] (already pulled)[/yellow]"
            )
            name = actual_name
        elif bin_:
            if Confirm.ask(f"    Pull [bold]{name}[/bold] now?", default=True):
                if subprocess.run([bin_, "pull", name]).returncode == 0:
                    console.print(f"    [green]✓ {name} ready.[/green]")
        else:
            console.print(f"    [yellow]Run: ollama pull {name}[/yellow]")

        return name

    planner_model = _pick_model("Planner", "gemma3:4b")
    coder_model   = _pick_model("Coder",   "qwen2.5-coder:3b")
    vision_model  = _pick_model("Vision",  "gemma3:4b")
    fast_model    = _pick_model("Fast",    "qwen2.5:3b")

    # Vision check
    _VIS_KW = {"vision", "vl", "llava", "minicpm", "gemma3"}
    has_vision = any(any(kw in m for kw in _VIS_KW) for m in pulled_bases)
    if not has_vision:
        console.print()
        console.print("[yellow]⚠ No vision model pulled yet.[/yellow]")
        bin_ = ollama_bin or _ollama_bin()
        if bin_ and Confirm.ask("  Pull gemma3:12b (multimodal, vision) now?", default=True):
            subprocess.run([bin_, "pull", "gemma3:12b"])
            console.print("  [green]✓ gemma3:12b ready.[/green]")
    console.print()

    # Benchmark
    if installed and running:
        console.print("[bold]Benchmarking your models...[/bold]")
        console.print("[dim]  Measuring cold-start speed for each role.[/dim]\n")
        unique_models = list(dict.fromkeys([planner_model, coder_model, vision_model, fast_model]))
        _ROLE_TOKENS = {"Planner": 400, "Coder": 5000, "Vision": 200, "Fast": 1500}

        bench_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2),
                            header_style="bold cyan")
        bench_table.add_column("Role")
        bench_table.add_column("Model", style="bold")
        bench_table.add_column("Speed",   justify="right")
        bench_table.add_column("Est. time", justify="right")

        results: dict[str, dict] = {}
        for m in unique_models:
            console.print(f"  [dim]Testing {m}...[/dim]", end="\r")
            results[m] = benchmark_model(m)

        for role, m in [("Planner", planner_model), ("Coder", coder_model),
                         ("Vision", vision_model), ("Fast", fast_model)]:
            r = results.get(m, {})
            if not r.get("ok"):
                bench_table.add_row(role, m, "[red]error[/red]", "—")
                continue
            tps = r["tps"]
            color  = "green" if tps >= 5 else "yellow" if tps >= 2 else "red"
            tokens = _ROLE_TOKENS.get(role, 500)
            est_m  = tokens / max(tps, 0.1) / 60
            color2 = "green" if est_m < 5 else "yellow" if est_m < 20 else "red"
            bench_table.add_row(
                role, m,
                f"[{color}]{tps:.1f} tok/s[/{color}]",
                f"[{color2}]~{est_m:.0f} min[/{color2}]",
            )

        console.print()
        console.print(bench_table)
        console.print()

    # Save to global config
    from . import config as _cfg
    key_prefix = fallback_prefix  # "" for primary, "fallback_" for fallback
    cfg_data = {
        f"{key_prefix}model":          coder_model,
        f"{key_prefix}planner_model":  planner_model,
        f"{key_prefix}coder_model":    coder_model,
        f"{key_prefix}vision_model":   vision_model,
        f"{key_prefix}fast_model":     fast_model,
    }
    if not key_prefix:
        cfg_data["backend"] = "ollama"
    _cfg.save_global_config(cfg_data)

    label = "fallback model roles" if key_prefix else "model roles"
    console.print(
        f"[green]✓ Ollama {label} saved.[/green]\n"
        f"  Planner : [cyan]{planner_model}[/cyan]\n"
        f"  Coder   : [cyan]{coder_model}[/cyan]\n"
        f"  Vision  : [cyan]{vision_model}[/cyan]\n"
        f"  Fast    : [cyan]{fast_model}[/cyan]"
    )
    return cfg_data


# ── Helper functions ───────────────────────────────────────────────────────────



def _setup_playwright() -> None:
    console.print("[bold]Checking Playwright (PDF export)...[/bold]")
    if Confirm.ask("  Install/verify Playwright Chromium?", default=True):
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=False,
        )
        if result.returncode == 0:
            console.print("  [green]✓ Chromium ready.[/green]")
        else:
            console.print("  [yellow]⚠ Playwright issues — PDF export may not work.[/yellow]")
    console.print()


# ── Main wizard ────────────────────────────────────────────────────────────────

def run() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Sarathi Setup — v1.0.0[/bold cyan]\n"
        "[dim]Configure your AI backend and model roles.[/dim]",
        border_style="cyan",
    ))
    console.print()

    # ── Mode selection ─────────────────────────────────────────────────────────
    console.print(Panel(
        "[bold]How do you want to run Sarathi?[/bold]\n\n"
        "  [cyan]1[/cyan]  [bold]Cloud only[/bold]    — OpenAI-compatible API\n"
        "             [dim](university proxy, Azure OpenAI, together.ai, LiteLLM)[/dim]\n\n"
        "  [cyan]2[/cyan]  [bold]Offline only[/bold]  — local Ollama models\n"
        "             [dim](runs entirely on your machine, no internet needed)[/dim]\n\n"
        "  [cyan]3[/cyan]  [bold]Cloud + Local[/bold] — cloud as primary, Ollama as offline fallback\n"
        "             [dim](best of both: speed + reliability)[/dim]",
        border_style="cyan", title="Setup Mode",
    ))

    while True:
        mode_input = console.input("  [bold]Choice[/bold] [dim][1/2/3][/dim]: ").strip()
        if mode_input in ("1", "2", "3"):
            break
        console.print("  [yellow]Please enter 1, 2, or 3.[/yellow]")
    mode = {"1": "cloud", "2": "offline", "3": "both"}[mode_input]
    console.print()

    # ── Hardware detection (always — useful context) ───────────────────────────
    console.print("[bold]Detecting your hardware...[/bold]")
    hw = detect_hardware()
    hw_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    hw_table.add_column(style="dim")
    hw_table.add_column(style="bold")
    hw_table.add_row("CPU",   hw["cpu_name"])
    hw_table.add_row("Cores", str(hw["cpu_cores"]))
    hw_table.add_row("RAM",   f"{hw['ram_total_gb']:.1f} GB  ·  "
                               f"[green]{hw['ram_avail_gb']:.1f} GB available[/green]")
    hw_table.add_row("GPU",   hw["gpu_name"])
    hw_table.add_row("VRAM",  f"{hw['vram_gb']:.1f} GB" if hw["vram_gb"] else "[dim]—[/dim]")
    hw_table.add_row("OS",    hw["os"])
    console.print(hw_table)
    if hw["vram_gb"] == 0 and mode != "cloud":
        console.print("[dim]  CPU-only — local models will be slow. Cloud mode is recommended.[/dim]")
    console.print()

    # ── Run selected mode ──────────────────────────────────────────────────────
    cloud_result = None

    if mode in ("cloud", "both"):
        console.print("[bold]Cloud API Setup[/bold]")
        cloud_result = _run_cloud_setup()
        if cloud_result is None:
            if mode == "cloud":
                console.print(
                    "[yellow]Cloud setup skipped. Falling back to offline setup.[/yellow]\n"
                )
                mode = "offline"
            else:
                console.print("[yellow]Cloud setup skipped — continuing with Ollama only.[/yellow]\n")
                mode = "offline"
        console.print()

    if mode in ("offline", "both"):
        label = "Offline Fallback Setup" if mode == "both" else "Offline Setup"
        console.print(f"[bold]{label}[/bold]")
        fallback_prefix = "fallback_" if mode == "both" else ""
        _run_offline_setup(hw, fallback_prefix=fallback_prefix)
        console.print()

    # ── Playwright ─────────────────────────────────────────────────────────────
    _setup_playwright()

    # ── Done ───────────────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold green]✓ Sarathi v1.0.0 is ready![/bold green]\n\n"
        "Get started:\n"
        "  [cyan]sarathi init[/cyan]  or  [cyan]sarathi join my-project/[/cyan]\n"
        "  [cyan]sarathi track my-project/[/cyan]  →  watch + auto-generate\n"
        "  [cyan]sarathi portfolio[/cyan]           →  dashboard at localhost:7432\n\n"
        "[dim]Run [bold]sarathi --help[/bold] for all commands.[/dim]",
        border_style="green",
    ))
