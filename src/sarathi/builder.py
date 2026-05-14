from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .scanner import ResultFile

# ── Domain detection ──────────────────────────────────────────────────────────

_ML_KEYWORDS = {
    "model", "training", "accuracy", "loss", "epoch", "dataset", "neural",
    "inference", "fine-tun", "classification", "regression", "embedding",
    "validation", "hyperparameter", "benchmark", "ablation",
}
_SW_KEYWORDS = {
    "refactor", "deploy", "api", "bug", "feature", "pull request", "release",
    "performance", "latency", "throughput", "test coverage", "sprint",
    "architecture", "microservice", "database", "endpoint",
}
_DATA_KEYWORDS = {
    "analysis", "insight", "correlation", "distribution", "eda",
    "exploratory", "notebook", "dashboard", "churn", "segment",
    "trend", "forecast", "cluster",
}


def detect_domain(description: str, files: list[ResultFile]) -> str:
    desc_lower = description.lower()
    ml_score = sum(1 for k in _ML_KEYWORDS if k in desc_lower)
    sw_score = sum(1 for k in _SW_KEYWORDS if k in desc_lower)
    da_score = sum(1 for k in _DATA_KEYWORDS if k in desc_lower)

    code_count = sum(1 for f in files if f.type == "code")
    data_count = sum(1 for f in files if f.type == "data")

    if code_count > 2 and data_count == 0:
        sw_score += 2
    if data_count > 2:
        da_score += 2
    if any(f.filename.endswith(".ipynb") for f in files):
        da_score += 1

    scores = {"ml": ml_score, "software": sw_score, "data": da_score}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "ml"


# ── Domain narrative configurations ──────────────────────────────────────────

_DOMAIN_CONFIG = {
    "ml": {
        "arc": "Pyramid arc: EDA/baseline → experiments → validation → optimized model at apex.",
        "arc_order": "Hypothesis → Data Overview → Experiments → Key Results → Ablation → Takeaways → Next Steps",
        "tone": "Empirical and Methodological. Interpret every metric — explain why it matters, not just what it is.",
        "hero_hint": "Key accuracy, F1, or loss reduction metric.",
        "special": (
            "Look for ablation study artifacts (files comparing model variants). "
            "If found, dedicate a slide to proving each component's contribution."
        ),
    },
    "software": {
        "arc": "Diamond arc: specific anecdote (bug/request) → systemic implications → architectural decision → validated outcome.",
        "arc_order": "Context/Problem → Architecture Before → Key Change → Implementation → Benchmarks/Tests → Results → Next Steps",
        "tone": "Architecture-Centric and Solution-Oriented. Frame every decision as solving a real constraint.",
        "hero_hint": "Latency reduction, throughput gain, test coverage %, or deploy frequency.",
        "special": (
            "Prioritize architecture diagrams and before/after comparisons. "
            "If code files are present, show the key logic change with a code slide."
        ),
    },
    "data": {
        "arc": "Inverted Pyramid + Kabob: lead with the single most important insight, then support it with data.",
        "arc_order": "Key Finding (FIRST!) → Data Overview → Deep Dive 1 → Deep Dive 2 → Correlations → Recommendations",
        "tone": "Insight-First and Persuasive. Apply the three-second rule: a viewer should grasp each slide's message in 3 seconds.",
        "hero_hint": "The single most surprising or actionable finding (a %, a trend, an anomaly).",
        "special": (
            "The first content slide MUST be the key finding, not background. "
            "Each slide should answer 'So what does this mean for the stakeholder?'"
        ),
    },
    "diff": {
        "arc": "Progress report: what changed, what improved, what's next.",
        "arc_order": "Overview of Changes → New/Modified Artifacts → Delta Metrics → Conclusions",
        "tone": "Comparative and Concise. Emphasize deltas, not absolute values.",
        "hero_hint": "The biggest improvement or most significant change between milestones.",
        "special": "Every slide should make the delta explicit — use 'Before: X → After: Y' framing.",
    },
}

# ── Pass 1: Planner prompt ────────────────────────────────────────────────────

_PLANNER_SYSTEM = """\
You are a world-class presentation strategist and data storyteller. Your job is to read \
a project's artifacts and git history, then design a compelling narrative outline for a \
Reveal.js slide deck.

Output ONLY a single valid JSON object — no prose, no markdown, no explanation.

═══════════════════════════════════════
EXACT OUTPUT SCHEMA (follow precisely)
═══════════════════════════════════════
{
  "title": "Punchy, specific presentation title (not just the project name)",
  "subtitle": "One sentence that frames what this presentation proves or shows",
  "domain": "ml | software | data | diff",
  "hero_metric": "The single most impressive number or outcome, e.g. '94.2% accuracy' or '3× faster' (null if none)",
  "slides": [
    {
      "id": 1,
      "type": "title | context | metric_callout | chart | image | code | comparison | takeaways | next_steps",
      "heading": "Specific, action-oriented heading — avoid generic labels like 'Results'",
      "artifacts": ["relative/path/to/file.csv"],
      "insight": "2-3 sentences. WHAT does this slide show? WHY does it matter? What should the audience think or feel?",
      "speaker_notes": "3-4 sentences of rich speaker notes — expand on the insight, add context not on the slide, suggest what to emphasize verbally.",
      "layout_hint": "r-fit-text | r-stretch | r-stack | auto-animate | (empty)",
      "bullet_points": ["Optional: 3-5 specific bullet points if this is a content slide"]
    }
  ]
}

══════════════════════
SLIDE COUNT & ORDERING
══════════════════════
- 10 to 14 slides total — enough to tell a complete story, not so many it drags
- Slide 1: always "title"
- Slide 2: "context" — WHY does this project exist? What problem does it solve?
- Middle slides: evidence, results, analysis — ordered by narrative arc (see domain instructions)
- Second-to-last: "takeaways" — the 3-5 things the audience must remember
- Last: "next_steps" — what happens next, open questions, or call to action

═══════════════════
SLIDE TYPE RULES
═══════════════════
metric_callout  → layout_hint: "r-fit-text". The hero metric front and center. Use when you have a standout number.
chart / image   → layout_hint: "r-stretch". The visual fills the slide. Heading is a conclusion, not a label.
code            → layout_hint: "auto-animate". Show the most important logic change, not the whole file.
comparison      → layout_hint: "r-stack". Before/after or option A vs B — use fragments to reveal.
takeaways       → 3-5 bullet points. Each one a complete, specific insight — not "accuracy improved" but "accuracy improved 12 points over the BERT baseline, closing 60% of the gap to GPT-4".
context / next_steps → layout_hint: "" (default layout).

═════════════════════
INSIGHT QUALITY BAR
═════════════════════
Bad:  "This chart shows the training loss over 50 epochs."
Good: "Training loss plateaued after epoch 35, suggesting the model saturated the dataset — increasing learning rate decay at epoch 20 could have saved 15 epochs of compute."

Bad:  "The refactor reduced latency."
Good: "Replacing synchronous DB calls with connection pooling cut p99 latency from 840ms to 95ms — a 9× improvement that unblocked the mobile team's 200ms SLA."

Every insight must answer: So what? Why does this matter? What does it mean for what comes next?

═══════════════════════
ARTIFACT ASSIGNMENT
═══════════════════════
- Only assign artifacts that genuinely belong on that slide
- Pre-rendered chart PNGs (in .sarathi/viz/) are preferred over raw CSVs for chart slides
- Images go on image/chart slides; code goes on code slides; text/notes inform the insight but don't need to be listed unless directly quoted
- A slide with no artifacts is fine — use it for context, takeaways, or transitions

══════════════════════
GIT HISTORY GUIDANCE
══════════════════════
If GitContext is provided:
- The commit messages tell the story of what was built and when — use them to construct the narrative arc
- Uncommitted changes are the most recent work — highlight them as "current state"
- Hot files (frequently changed) indicate the core components — feature them in the presentation
- Infer the project's progress: early commits = setup; recent commits = polish and fixes
"""


def _planner_user(project_name: str, description: str, domain: str,
                  files: list[ResultFile],
                  git_ctx_text: str | None = None) -> str:
    dc = _DOMAIN_CONFIG.get(domain, _DOMAIN_CONFIG["ml"])
    file_list = "\n".join(f"  - [{f.type}] {f.path}" for f in files)

    git_block = ""
    if git_ctx_text:
        git_block = f"\n<GitContext>\n{git_ctx_text}\n</GitContext>\n"

    return (
        f"<ProjectContext>\n"
        f"Project: {project_name}\n"
        f"Description: {description}\n"
        f"Domain: {domain}\n"
        f"Narrative arc: {dc['arc']}\n"
        f"Slide order: {dc['arc_order']}\n"
        f"Tone: {dc['tone']}\n"
        f"Hero metric hint: {dc['hero_hint']}\n"
        f"Special instructions: {dc['special']}\n"
        f"</ProjectContext>\n"
        f"{git_block}\n"
        f"<ArtifactList>\n{file_list}\n</ArtifactList>\n\n"
        f"Generate the JSON outline now."
    )


# ── Pass 2: Coder prompt ──────────────────────────────────────────────────────

_CODER_SYSTEM = """\
You are an elite Reveal.js slide engineer. You write beautiful, production-quality HTML \
slides that combine visual impact with clear communication.

Output ONLY this exact structure — no prose, no markdown, no explanation:
<html_code>
<section ...attributes...>
  ...slide HTML...
  <aside class="notes">speaker notes</aside>
</section>
</html_code>

═══════════════════════════
SLIDE TYPE IMPLEMENTATIONS
═══════════════════════════

TITLE SLIDE:
<section data-auto-animate>
  <h1>PROJECT TITLE</h1>
  <p class="subtitle">One-sentence framing of what this presentation proves</p>
  <p class="subtitle" style="margin-top:1.5em;font-size:.6em">Month Year</p>
  <aside class="notes">...</aside>
</section>

METRIC CALLOUT (hero number — use r-fit-text so it fills the slide):
<section data-auto-animate>
  <p style="color:var(--accent);font-size:.7em;text-transform:uppercase;letter-spacing:.1em">KEY RESULT</p>
  <h2 class="r-fit-text hero-metric">94.2%</h2>
  <p class="subtitle">What this number means and why it matters</p>
  <aside class="notes">...</aside>
</section>

CHART / IMAGE (visual fills all available space):
<section data-auto-animate>
  <h2>Conclusion-as-heading, not a label</h2>
  <img class="r-stretch" src="EXACT_DATA_URI_HERE" alt="description">
  <p style="font-size:.55em;color:var(--fg2)">One-line annotation explaining what to look at</p>
  <aside class="notes">...</aside>
</section>

CONTENT / BULLETS (max 5 bullets, each a complete insight):
<section data-auto-animate>
  <h2>Specific heading</h2>
  <ul>
    <li class="fragment">Complete insight, not a topic label</li>
    <li class="fragment">Each bullet answers: so what?</li>
  </ul>
  <aside class="notes">...</aside>
</section>

CODE SLIDE (show only the key change, not the whole file):
<section data-auto-animate>
  <h2>The critical change</h2>
  <pre><code class="language-python" data-trim data-line-numbers="3,7">
# only the relevant snippet — 10-20 lines max
def key_function():
    ...
  </code></pre>
  <p class="subtitle">One sentence on why this change matters</p>
  <aside class="notes">...</aside>
</section>

COMPARISON (before/after or A vs B — fragments reveal each):
<section data-auto-animate>
  <h2>What changed</h2>
  <div class="r-stack">
    <div class="fragment fade-out" style="width:100%">
      <h3 style="color:var(--fg2)">Before</h3>
      <!-- before content -->
    </div>
    <div class="fragment" style="width:100%">
      <h3 style="color:var(--accent)">After</h3>
      <!-- after content -->
    </div>
  </div>
  <aside class="notes">...</aside>
</section>

TAKEAWAYS:
<section data-auto-animate>
  <h2>Key Takeaways</h2>
  <ul>
    <li class="fragment">Specific, complete insight #1 with a number or outcome</li>
    <li class="fragment">Specific, complete insight #2</li>
    <li class="fragment">Specific, complete insight #3</li>
  </ul>
  <aside class="notes">...</aside>
</section>

═══════════════
CRITICAL RULES
═══════════════
1. NEVER add <style> tags — CSS variables (--accent, --fg, --fg2, --dim) are globally injected.
2. Images: use the EXACT data URI provided in full — do not shorten, truncate, or re-encode.
3. Code: use <pre><code> with the correct language class. Never show more than 20 lines.
4. Headings: write conclusions, not labels. "Loss Plateaued at Epoch 35" not "Training Loss".
5. Bullets: each one must be a complete, specific insight. No single-word bullets.
6. data-auto-animate: add to <section> on slides that follow a related slide — enables smooth transitions.
7. Speaker notes: 3-4 sentences. Expand on what's on the slide. Add context not visible in the visual.
8. Fragment class on list items: reveal one at a time for better pacing.

CSS classes available: r-fit-text, r-stretch, r-stack, fragment, fade-out, hero-metric, subtitle
CSS variables available: --accent (#4fc3f7), --accent2 (#f48fb1), --fg, --fg2, --dim, --bg
"""


def _coder_user(slide: dict, artifacts_map: dict[str, ResultFile]) -> str:
    artifact_blocks = []
    for path in slide.get("artifacts", []):
        rf = artifacts_map.get(path)
        if rf is None:
            continue
        if rf.type in ("image", "svg"):
            artifact_blocks.append(
                f"[IMAGE artifact: {rf.filename}]\n"
                f"Use this exact data URI as the src: {rf.content[:120]}..."
                f"\n(full URI available — use it verbatim)"
            )
            # Pass full URI separately so LLM can use it
            artifact_blocks.append(f"FULL_URI_{rf.filename}: {rf.content}")
        elif rf.type == "data":
            artifact_blocks.append(
                f"[DATA: {rf.filename}]\n{rf.content[:1500]}"
                + ("\n...(truncated)" if len(rf.content) > 1500 else "")
            )
        elif rf.type in ("text", "code"):
            artifact_blocks.append(
                f"[{rf.type.upper()}: {rf.filename}]\n{rf.content[:1500]}"
                + ("\n...(truncated)" if len(rf.content) > 1500 else "")
            )

    artifacts_text = "\n\n".join(artifact_blocks) if artifact_blocks else "(no artifacts)"

    return (
        f"<SlideSpec>\n"
        f"id: {slide['id']}\n"
        f"type: {slide['type']}\n"
        f"heading: {slide['heading']}\n"
        f"insight: {slide.get('insight', '')}\n"
        f"layout_hint: {slide.get('layout_hint', '')}\n"
        f"speaker_notes: {slide.get('speaker_notes', '')}\n"
        f"</SlideSpec>\n\n"
        f"<Artifacts>\n{artifacts_text}\n</Artifacts>\n\n"
        f"Generate the <section> HTML now."
    )


# ── HTML assembly ─────────────────────────────────────────────────────────────

_THEMES: dict[str, str] = {
    "dark-gradient": """
        :root {
            --bg-start: #0d0d1a;
            --bg-end: #1a1a2e;
            --accent: #4fc3f7;
            --accent2: #f48fb1;
            --fg: #e8e8f0;
            --dim: #8888aa;
        }
        .reveal-viewport { background: linear-gradient(135deg, var(--bg-start), var(--bg-end)); }
        .reveal { color: var(--fg); font-family: 'Inter', sans-serif; }
        .reveal h1, .reveal h2, .reveal h3 { color: var(--accent); font-weight: 700; letter-spacing: -0.02em; }
        .reveal h1 { font-size: 2.2em; }
        .reveal h2 { font-size: 1.6em; }
        .reveal section { padding: 40px 60px; }
        .reveal ul li { margin: 0.4em 0; }
        .reveal pre code { background: #111122; border-radius: 8px; padding: 1em; }
        .reveal .controls { color: var(--accent); }
        .reveal .progress { background: var(--accent2); }
        .reveal .slide-number { color: var(--dim); }
        .subtitle { color: var(--dim); font-size: 0.75em; margin-top: 0.3em; }
        .hero-metric { color: var(--accent); line-height: 1; }
    """,
    "dracula": """
        :root { --bg: #282a36; --fg: #f8f8f2; --accent: #bd93f9; --green: #50fa7b; --pink: #ff79c6; }
        .reveal-viewport { background: var(--bg); }
        .reveal { color: var(--fg); font-family: 'Inter', sans-serif; }
        .reveal h1, .reveal h2, .reveal h3 { color: var(--accent); }
        .reveal .progress { background: var(--green); }
        .subtitle { color: #6272a4; font-size: 0.75em; }
        .hero-metric { color: var(--green); }
    """,
    "light": """
        :root { --bg: #fafafa; --fg: #1a1a2e; --accent: #1565c0; }
        .reveal-viewport { background: var(--bg); }
        .reveal { color: var(--fg); font-family: 'Inter', sans-serif; }
        .reveal h1, .reveal h2, .reveal h3 { color: var(--accent); }
        .reveal section { padding: 40px 60px; }
        .subtitle { color: #666; font-size: 0.75em; }
        .hero-metric { color: var(--accent); }
    """,
    "minimal": """
        :root { --bg: #111; --fg: #eee; --accent: #fff; }
        .reveal-viewport { background: var(--bg); }
        .reveal { color: var(--fg); font-family: 'Inter', sans-serif; }
        .reveal h1, .reveal h2, .reveal h3 { color: var(--accent); font-weight: 300; letter-spacing: 0.05em; }
        .subtitle { color: #888; font-size: 0.75em; }
        .hero-metric { color: var(--accent); }
    """,
}


def _assemble(title: str, slides_html: list[str], theme: str) -> str:
    theme_css = _THEMES.get(theme, _THEMES["dark-gradient"])
    slides_joined = "\n".join(slides_html)
    from datetime import date
    today = date.today().strftime("%B %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/reveal.js@4/dist/reveal.css">
<style>
{theme_css}
.reveal pre, .reveal code {{ font-family: 'JetBrains Mono', monospace; }}
.reveal .r-fit-text {{ line-height: 1; }}
</style>
</head>
<body>
<div class="reveal">
  <div class="slides">
{slides_joined}
  </div>
</div>
<script src="https://unpkg.com/reveal.js@4/dist/reveal.js"></script>
<script src="https://unpkg.com/reveal.js@4/plugin/highlight/highlight.js"></script>
<script src="https://unpkg.com/reveal.js@4/plugin/notes/notes.js"></script>
<script>
Reveal.initialize({{
  hash: true,
  slideNumber: true,
  transition: 'slide',
  transitionSpeed: 'default',
  autoAnimateEasing: 'cubic-bezier(0.25, 1, 0.5, 1)',
  autoAnimateDuration: 0.6,
  plugins: [ RevealHighlight, RevealNotes ]
}});
</script>
</body>
</html>"""


# ── HTML extraction helpers ───────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*)", text, re.DOTALL | re.IGNORECASE)
    if fence:
        inner = fence.group(1)
        closing = inner.rfind("```")
        if closing != -1:
            inner = inner[:closing]
        text = inner.strip()

    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]

    return json.loads(text)


def _extract_section(text: str) -> str:
    m = re.search(r"<html_code>\s*(.*?)\s*</html_code>", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    m = re.search(r"(<section[\s>].*?</section>)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return f"<section><h2>Slide</h2><p>{text[:200]}</p></section>"


# ── Public API ────────────────────────────────────────────────────────────────

def generate(
    project_name: str,
    description: str,
    files: list[ResultFile],
    model: str,
    output_html: Path,
    project_dir: Path,
    theme: str = "dark-gradient",
    outline_path: Path | None = None,
    domain_override: str | None = None,
    git_ctx_text: str | None = None,
    verbose: bool = False,
    fast: bool = False,
    planner_model: str | None = None,
    coder_model: str | None = None,
    vision_model: str | None = None,
    fast_model: str | None = None,
) -> None:
    # Role-specific model routing — fall back to `model` if roles not set
    _planner = planner_model or model
    _coder   = coder_model   or model
    _vision  = vision_model  or model
    _fast    = fast_model    or _coder  # --fast uses dedicated small model

    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich import box as rbox
    from . import viz as viz_module
    import time

    console = Console()

    # ── Preload models into RAM ───────────────────────────────────────────────
    unique_models = list(dict.fromkeys(
        [_fast] if fast else [_planner, _coder] +
        ([_vision] if _vision != _planner else [])
    ))
    console.print()
    console.print("[bold][sarathi] Loading models into RAM...[/bold]")

    load_table = Table(box=rbox.SIMPLE, show_header=True, padding=(0, 2),
                       header_style="bold cyan")
    load_table.add_column("Role")
    load_table.add_column("Model", style="bold")
    load_table.add_column("Status", justify="right")
    load_table.add_column("Load time", justify="right")

    role_map = {_planner: "Planner", _coder: "Coder"}
    if _vision and _vision != _planner:
        role_map[_vision] = "Vision"

    for m in unique_models:
        role = role_map.get(m, "Model")
        console.print(f"  [dim]Loading {m}...[/dim]", end="\r")
        t0 = time.perf_counter()
        try:
            import ollama as _ollama
            # Warmup request — loads model, keep alive for the duration of generation
            _ollama.generate(model=m, prompt="ready", options={"num_predict": 1})
            load_s = time.perf_counter() - t0
            load_table.add_row(
                role, m,
                "[green]✓ loaded[/green]",
                f"[dim]{load_s:.1f}s[/dim]"
            )
        except Exception as exc:
            load_s = time.perf_counter() - t0
            load_table.add_row(role, m, "[red]✗ error[/red]", f"[dim]{str(exc)[:30]}[/dim]")

    console.print()
    console.print(load_table)
    console.print()

    # Pre-render CSVs to chart images
    csv_files = [f for f in files if f.type == "data" and f.filename.endswith(".csv")]
    if csv_files:
        console.print(f"[dim][sarathi][/dim] Pre-rendering {len(csv_files)} chart(s)...")
    viz_files = viz_module.process(files, project_dir)
    all_files = files + viz_files

    # Context trimming — fast mode or large file sets get aggressive limits
    if fast:
        all_files = _trim_context(all_files, max_chars=6000, max_files=8)
        console.print(
            f"[dim][sarathi][/dim] Fast mode — using {len(all_files)} file(s) "
            f"(trimmed for speed)"
        )
    elif len(all_files) > 12 or sum(len(f.content) for f in all_files) > 20000:
        all_files = _trim_context(all_files, max_chars=15000, max_files=12)
        console.print(
            f"[dim][sarathi][/dim] Large project — trimmed to {len(all_files)} "
            f"most relevant file(s)"
        )

    # Build artifacts lookup
    artifacts_map: dict[str, ResultFile] = {rf.path: rf for rf in all_files}
    for rf in all_files:
        artifacts_map[rf.filename] = rf

    domain = domain_override or detect_domain(description, files)
    console.print(f"[dim][sarathi][/dim] Domain detected: [cyan]{domain}[/cyan]")

    if fast:
        console.print(
            f"[dim][sarathi][/dim] Fast mode — single-pass "
            f"([bold]{_fast}[/bold])..."
        )
        with Progress(SpinnerColumn(), TextColumn("[dim]generating...[/dim]"),
                      console=console, transient=True):
            html_doc = _generate_single_pass(
                project_name, description, domain, all_files, _fast,
                theme, git_ctx_text, verbose=verbose
            )
        output_html.write_text(html_doc, encoding="utf-8")
        console.print(f"[green][sarathi][/green] Presentation ready (single-pass).")
        return

    # ── Two-pass: outline → slide-by-slide (better quality) ──────────────────
    if outline_path and outline_path.exists():
        console.print(f"[dim][sarathi][/dim] Loading outline from {outline_path.name}...")
        outline = json.loads(outline_path.read_text(encoding="utf-8"))
    else:
        console.print(
            f"[dim][sarathi][/dim] Pass 1 — planning narrative outline "
            f"([bold]{_planner}[/bold])..."
        )
        outline = _generate_outline(
            project_name, description, domain, all_files, _planner, git_ctx_text,
            verbose=verbose,
        )
        n_slides = len(outline.get("slides", []))
        title = outline.get("title", project_name)
        console.print(
            f"[green][sarathi][/green] Outline ready: [bold]{title}[/bold] "
            f"— {n_slides} slides planned"
        )
        if outline_path:
            outline_path.parent.mkdir(parents=True, exist_ok=True)
            outline_path.write_text(json.dumps(outline, indent=2), encoding="utf-8")
            return

    slides = outline.get("slides", [])
    slides_html: list[str] = []

    console.print(
        f"[dim][sarathi][/dim] Pass 2 — rendering slides ([bold]{_coder}[/bold])"
    )
    with Progress(
        SpinnerColumn(),
        TextColumn("[dim][sarathi][/dim]"),
        TextColumn("[cyan]{task.description}[/cyan]"),
        BarColumn(bar_width=24),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("rendering", total=len(slides))
        for slide in slides:
            heading = slide.get("heading", f"Slide {slide.get('id', '')}")
            progress.update(task, description=f"[bold]{heading[:50]}[/bold]")
            try:
                html = _render_slide(slide, artifacts_map, _coder, verbose=verbose)
            except Exception as exc:
                html = (
                    f"<section><h2>{heading}</h2>"
                    f"<p style='color:#f48fb1'>Render error: {exc}</p></section>"
                )
            slides_html.append(html)
            progress.advance(task)

    console.print(f"[green][sarathi][/green] All {len(slides_html)} slides rendered.")

    html_doc = _assemble(outline.get("title", project_name), slides_html, theme)

    html_doc = _assemble(outline.get("title", project_name), slides_html, theme)
    output_html.write_text(html_doc, encoding="utf-8")

    # PPTX — tag each slide with theme so the exporter can use it
    for s in outline.get("slides", []):
        s["_theme"] = theme
    try:
        from . import pptx_exporter
        pptx_out = output_html.with_suffix(".pptx")
        pptx_exporter.to_pptx(outline, artifacts_map, pptx_out)
    except Exception:
        pass  # PPTX is best-effort; HTML is primary


def _trim_context(files: list[ResultFile], max_chars: int, max_files: int) -> list[ResultFile]:
    """Keep priority files first, then trim by char budget and file count."""
    # Priority order: images > data > text/priority docs > code
    priority = {"image": 0, "svg": 1, "data": 2, "text": 3, "code": 4}
    sorted_files = sorted(files, key=lambda f: priority.get(f.type, 5))

    kept, total_chars = [], 0
    for rf in sorted_files:
        if len(kept) >= max_files:
            break
        content_len = len(rf.content)
        if total_chars + content_len > max_chars and kept:
            # Include a truncated version of important text files
            if rf.type in ("text", "code") and len(kept) < max_files:
                remaining = max_chars - total_chars
                if remaining > 200:
                    truncated = ResultFile(
                        path=rf.path, filename=rf.filename, type=rf.type,
                        content=rf.content[:remaining] + "\n...(trimmed)"
                    )
                    kept.append(truncated)
            break
        kept.append(rf)
        total_chars += content_len
    return kept


def _generate_single_pass(
    project_name: str,
    description: str,
    domain: str,
    files: list[ResultFile],
    model: str,
    theme: str,
    git_ctx_text: str | None,
    verbose: bool = False,
) -> str:
    """Generate a complete Reveal.js HTML presentation in one LLM call."""
    dc = _DOMAIN_CONFIG.get(domain, _DOMAIN_CONFIG["ml"])
    theme_css = _THEMES.get(theme, _THEMES["dark-gradient"])

    file_parts: list[str] = []
    for rf in files:
        if rf.type in ("image", "svg"):
            file_parts.append(f"[IMAGE: {rf.filename}]\n<img src=\"{rf.content}\">")
        elif rf.type == "data":
            file_parts.append(f"[DATA: {rf.filename}]\n{rf.content[:800]}")
        else:
            file_parts.append(f"[{rf.type.upper()}: {rf.filename}]\n{rf.content[:600]}")

    git_block = f"\n<GitContext>\n{git_ctx_text}\n</GitContext>" if git_ctx_text else ""

    system = f"""\
You are an expert Reveal.js presentation engineer. Generate a complete, self-contained \
HTML presentation. Output ONLY the full HTML document — nothing else.

Theme CSS to inject inline:
{theme_css}

Narrative arc for {domain}: {dc['arc']}
Tone: {dc['tone']}
Use 6-8 slides. Use data-auto-animate, r-fit-text for hero metrics, r-stretch for images.
Each section must have <aside class="notes">.
"""

    user = (
        f"Project: {project_name}\nDescription: {description}\n"
        f"{git_block}\n\nFiles:\n" + "\n\n".join(file_parts) +
        "\n\nGenerate the complete Reveal.js HTML now."
    )

    from datetime import date
    text = _chat(model, system, user, verbose=verbose)

    # Extract HTML
    start = text.find("<!DOCTYPE")
    if start == -1:
        start = text.find("<html")
    if start != -1:
        return text[start:]

    # Fallback: wrap whatever came back
    return _assemble(project_name, [f"<section><p>{text[:500]}</p></section>"], theme)


_OLLAMA_BASE = "http://localhost:11434"
_OLLAMA_KEY  = "ollama"


def _claude_cli_available() -> bool:
    import shutil
    return shutil.which("claude") is not None


def _chat_via_claude_code(model: str, system: str, user: str,
                          verbose: bool = False) -> str:
    """Stream generation through Claude Code CLI → Ollama.

    Uses --output-format stream-json so we can parse events for live progress.
    ANTHROPIC_API_KEY must be empty; ANTHROPIC_AUTH_TOKEN=ollama routes to Ollama.
    """
    import subprocess, json, sys, time

    env = {
        **os.environ,
        "ANTHROPIC_BASE_URL":   os.environ.get("ANTHROPIC_BASE_URL",   _OLLAMA_BASE),
        "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN", _OLLAMA_KEY),
        "ANTHROPIC_API_KEY":    "",   # empty → claude uses ANTHROPIC_AUTH_TOKEN
    }

    cmd = [
        "claude",
        "--model", model,
        "--print",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
        "--bare",
        "--system-prompt", system,
        "-p", user,
    ]

    chunks: list[str] = []
    out_tokens = 0
    in_tokens  = 0
    t0         = time.perf_counter()
    est_in     = (len(system) + len(user)) // 4

    def _show() -> None:
        elapsed = time.perf_counter() - t0
        tps     = out_tokens / max(elapsed, 0.5)
        in_str  = f"{in_tokens:,}" if in_tokens else f"~{est_in:,}"
        elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
        bar  = "█" * min(out_tokens // 20, 30) + "░" * max(0, 30 - out_tokens // 20)
        line = (
            f"  [{bar}]  prompt {in_str} → out {out_tokens}"
            f"  {tps:.1f} tok/s  {elapsed_str}"
        )
        sys.stdout.write(f"\r{line:<100}")
        sys.stdout.flush()

    proc = subprocess.Popen(
        cmd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    if verbose:
        print(f"  [claude] cmd: {' '.join(cmd[:6])} ...")
        print(f"  [claude] ANTHROPIC_BASE_URL={env.get('ANTHROPIC_BASE_URL')}")

    try:
        for raw_line in proc.stdout:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            if verbose:
                print(f"\n[stream-json] {raw_line[:120]}")

            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                # Plain text fallback — claude printed raw output
                chunks.append(raw_line)
                out_tokens += 1
                _show()
                continue

            etype = event.get("type", "")

            if etype == "system":
                # First event — may contain model/session info
                pass
            elif etype == "assistant":
                # Content block from assistant
                content = event.get("message", {}).get("content", [])
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        chunks.append(text)
                        out_tokens += max(len(text.split()), 1)
                        _show()
            elif etype == "content_block_delta":
                delta = event.get("delta", {})
                text  = delta.get("text", "")
                if text:
                    chunks.append(text)
                    out_tokens += 1
                    if out_tokens % 5 == 0:
                        _show()
            elif etype == "message_start":
                usage = event.get("message", {}).get("usage", {})
                in_tokens = usage.get("input_tokens", 0)
                _show()
            elif etype == "result":
                # Claude Code final result event — contains full text
                result_text = event.get("result", "")
                if result_text and not chunks:
                    chunks.append(result_text)
                    out_tokens = len(result_text.split())
                _show()

        proc.wait(timeout=30)
    except Exception as exc:
        proc.kill()
        raise RuntimeError(f"claude stream error: {exc}") from exc

    # Capture stderr for diagnostics
    stderr_out = ""
    if proc.stderr:
        try:
            stderr_out = proc.stderr.read(800).strip()
        except Exception:
            pass

    # Final summary line
    elapsed = time.perf_counter() - t0
    tps     = out_tokens / max(elapsed, 0.001)
    in_str  = f"{in_tokens:,}" if in_tokens else f"~{est_in:,}"
    sys.stdout.write("\r" + " " * 100 + "\r")
    sys.stdout.flush()
    print(f"  ✓  in: {in_str}  ·  out: {out_tokens}  ·  {tps:.1f} tok/s  ·  {elapsed:.0f}s")

    if proc.returncode not in (0, None):
        raise RuntimeError(
            f"claude exited {proc.returncode}"
            + (f": {stderr_out}" if stderr_out else "")
        )

    output = "".join(chunks).strip()
    if not output:
        err_detail = f" stderr: {stderr_out}" if stderr_out else ""
        raise RuntimeError(f"claude CLI returned empty output.{err_detail}")
    return output


def _chat_via_sdk(model: str, system: str, user: str, verbose: bool = False) -> str:
    import anthropic
    from rich.console import Console
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich.panel import Panel

    base_url = os.environ.get("ANTHROPIC_BASE_URL", _OLLAMA_BASE)
    api_key  = os.environ.get("ANTHROPIC_AUTH_TOKEN",
               os.environ.get("ANTHROPIC_API_KEY", _OLLAMA_KEY))

    if verbose:
        _vc = Console()
        _vc.print(Rule("[bold cyan]PROMPT → SYSTEM[/bold cyan]", style="cyan"))
        _vc.print(Syntax(system[:3000] + ("..." if len(system) > 3000 else ""),
                         "text", theme="monokai", word_wrap=True))
        _vc.print(Rule("[bold cyan]PROMPT → USER[/bold cyan]", style="cyan"))
        _vc.print(Syntax(user[:3000] + ("..." if len(user) > 3000 else ""),
                         "text", theme="monokai", word_wrap=True))

    import time
    from rich.live import Live
    from rich.text import Text

    client = anthropic.Anthropic(base_url=base_url, api_key=api_key)

    import sys

    chunks: list[str] = []
    out_tokens = 0
    in_tokens  = 0
    t0         = time.perf_counter()
    est_in     = (len(system) + len(user)) // 4

    def _print_progress() -> None:
        elapsed  = time.perf_counter() - t0
        tps      = out_tokens / max(elapsed, 0.5)   # avoid 0.0 at start
        in_str   = f"{in_tokens:,}" if in_tokens else f"~{est_in:,}"
        elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
        bar_full = min(out_tokens // 20, 30)        # fills as tokens come in
        bar      = "█" * bar_full + "░" * (30 - bar_full)
        line     = (
            f"  [{bar}]  "
            f"prompt {in_str} → generating {out_tokens}  "
            f"  {tps:.1f} tok/s  {elapsed_str}"
        )
        sys.stdout.write(f"\r{line:<100}")
        sys.stdout.flush()

    with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "message_start":
                usage = getattr(getattr(event, "message", None), "usage", None)
                if usage:
                    in_tokens = getattr(usage, "input_tokens", 0)
                _print_progress()
            elif event_type == "content_block_delta":
                delta = getattr(event, "delta", None)
                chunk = getattr(delta, "text", "") if delta else ""
                if chunk:
                    chunks.append(chunk)
                    out_tokens += 1
                    # Update every 5 tokens — smooth but not excessive
                    if out_tokens % 5 == 0:
                        _print_progress()

    # Move to next line and print final summary
    elapsed = time.perf_counter() - t0
    tps     = out_tokens / max(elapsed, 0.001)
    in_str  = str(in_tokens) if in_tokens else f"~{est_in}"
    sys.stdout.write("\r" + " " * 82 + "\r")   # clear the progress line
    sys.stdout.flush()
    Console().print(
        f"  [green]✓[/green]  "
        f"in: [dim]{in_str}[/dim]  ·  "
        f"out: [bold]{out_tokens}[/bold]  ·  "
        f"[bold]{tps:.1f} tok/s[/bold]  ·  {elapsed:.0f}s"
    )

    text = "".join(chunks)

    if verbose:
        _vc.print(Rule("[bold green]RESPONSE[/bold green]", style="green"))
        _vc.print(Panel(
            text[:4000] + ("..." if len(text) > 4000 else ""),
            border_style="green", expand=False
        ))

    return text


def _chat_via_ollama(model: str, system: str, user: str,
                     verbose: bool = False) -> str:
    """Stream generation via Ollama's native Python SDK — reliable, real tok/s."""
    import ollama as _ollama
    import time, sys

    if verbose:
        from rich.console import Console as _C
        from rich.rule import Rule
        c = _C()
        c.print(Rule("[bold cyan]PROMPT → SYSTEM[/bold cyan]", style="cyan"))
        c.print(system[:3000] + ("..." if len(system) > 3000 else ""))
        c.print(Rule("[bold cyan]PROMPT → USER[/bold cyan]", style="cyan"))
        c.print(user[:3000] + ("..." if len(user) > 3000 else ""))

    messages = [
        {"role": "system",    "content": system},
        {"role": "user",      "content": user},
    ]

    chunks: list[str] = []
    out_tokens = 0
    est_in     = (len(system) + len(user)) // 4
    t0         = time.perf_counter()
    BAR_MAX    = 40

    def _show(done: bool = False) -> None:
        elapsed = time.perf_counter() - t0
        tps     = out_tokens / max(elapsed, 0.5)
        elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
        filled  = min(out_tokens // 15, BAR_MAX)
        bar     = "█" * filled + "░" * (BAR_MAX - filled)
        sym     = "✓" if done else "⟳"
        line    = (
            f"  {sym} [{bar}]  "
            f"in ~{est_in:,}  out {out_tokens}  "
            f"  {tps:.1f} tok/s  {elapsed_str}"
        )
        sys.stdout.write(f"\r{line:<110}")
        sys.stdout.flush()

    _show()

    for chunk in _ollama.chat(model=model, messages=messages, stream=True):
        text = chunk.get("message", {}).get("content", "")
        if text:
            chunks.append(text)
            out_tokens += 1
            if out_tokens % 3 == 0:
                _show()

    sys.stdout.write("\r" + " " * 112 + "\r")
    sys.stdout.flush()
    _show(done=True)
    print()   # newline after final summary

    result = "".join(chunks)

    if verbose:
        from rich.console import Console as _C
        from rich.rule import Rule
        from rich.panel import Panel
        c = _C()
        c.print(Rule("[bold green]RESPONSE[/bold green]", style="green"))
        c.print(Panel(result[:4000] + ("..." if len(result) > 4000 else ""),
                      border_style="green", expand=False))

    return result


def _chat(model: str, system: str, user: str, verbose: bool = False) -> str:
    return _chat_via_ollama(model, system, user, verbose=verbose)


def _generate_outline(
    project_name: str,
    description: str,
    domain: str,
    files: list[ResultFile],
    model: str,
    git_ctx_text: str | None = None,
    verbose: bool = False,
) -> dict:
    user_msg = _planner_user(project_name, description, domain, files, git_ctx_text)
    text = _chat(model, _PLANNER_SYSTEM, user_msg, verbose=verbose)
    return _extract_json(text)


def _render_slide(
    slide: dict,
    artifacts_map: dict[str, ResultFile],
    model: str,
    verbose: bool = False,
) -> str:
    user_msg = _coder_user(slide, artifacts_map)
    text = _chat(model, _CODER_SYSTEM, user_msg, verbose=verbose)
    return _extract_section(text)
