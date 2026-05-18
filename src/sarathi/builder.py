from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .scanner import ResultFile

# Populated by _chat_via_ollama/_chat_via_openai; read by generate() for stats
_last_gen_tps: float = 0.0

# Set at the start of generate() from loaded config; read by _chat()
_cloud_config: dict = {}

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
You are a world-class presentation strategist. Your job: read a project's files and git \
history, then design a narrative outline that tells the REAL story of this specific project.

Output ONLY a single valid JSON object — no prose, no markdown fences, no explanation.

══════════════════════════════
CARDINAL RULE — GROUND IN REALITY
══════════════════════════════
Every slide heading, insight, and bullet point must come directly from the files and git \
history provided. Never invent metrics, never use "[placeholder]" text, never describe \
things that aren't in the artifacts. If you don't see a number, don't make one up.
Quote actual commit messages, actual function names, actual file names.
A slide that says nothing specific is worse than no slide at all.

═══════════════════════════════════════
OUTPUT SCHEMA
═══════════════════════════════════════
{
  "title": "Specific title derived from the actual project — not just the project name",
  "subtitle": "One sentence stating what this project does or proved, using real details",
  "domain": "ml | software | data | diff",
  "hero_metric": "A real number or outcome from the files (null if none found)",
  "slides": [
    {
      "id": 1,
      "type": "title | context | metric_callout | chart | image | code | comparison | takeaways | next_steps",
      "heading": "A conclusion drawn from real evidence — not a label like 'Results'",
      "artifacts": ["exact/path/from/artifact/list"],
      "insight": "2-3 sentences grounded in real content. WHAT does this slide show from the actual files? WHY does it matter for this project specifically?",
      "speaker_notes": "3-4 sentences that expand on the slide. Reference specific details from the files. What should the presenter emphasize?",
      "layout_hint": "r-fit-text | r-stretch | r-stack | auto-animate | (empty)",
      "bullet_points": ["3-5 specific, complete bullets — each references real content"]
    }
  ]
}

══════════════════════
SLIDE COUNT & ORDERING
══════════════════════
- 10 to 14 slides total
- Slide 1: title — project name + one real sentence about what it does
- Slide 2: context — the real problem this project solves (from README/CLAUDE.md)
- Middle: evidence in narrative order (see domain arc below)
- Second-to-last: takeaways — 3-5 specific things learned, grounded in actual work
- Last: next_steps — concrete next actions visible from the current state

═══════════════════
SLIDE TYPES
═══════════════════
metric_callout → layout_hint "r-fit-text". A real number from the files, big and centred.
chart/image    → layout_hint "r-stretch". Heading states the conclusion from the visual.
code           → layout_hint "auto-animate". The most important 5-10 lines — never a whole file.
comparison     → layout_hint "r-stack". Before vs after — only if both states appear in the files.
table          → layout_hint "". CSV data as a styled HTML table, max 8 rows, one insight heading.
takeaways      → 3-5 bullets. Each is a complete sentence with a specific detail.
context/next_steps → layout_hint "" (default).

══════════════════════════════
SLIDE VARIETY RULES — MANDATORY
══════════════════════════════
1. You MUST use at least 4 different slide types across the deck.
2. If ANY image or chart file is in the artifact list → you MUST include at least one "image" or "chart" slide.
3. If ANY CSV file is in the artifact list → you MUST include at least one "metric_callout" slide with a real number from that data, OR a "table" slide.
4. "code" slides are limited to MAX 2 per deck. Use "metric_callout", "table", or "comparison" instead of dumping code.
5. NEVER produce a deck where all slides are "context" or bullet-only. That is a failure.

══════════════════════════
INSIGHT QUALITY — EXAMPLES
══════════════════════════
BAD (generic, invented):
  "The model achieved high accuracy after training."
GOOD (specific, grounded):
  "Loss plateaued at epoch 35 per the training log — the model saturated the dataset, \
   suggesting the next experiment should try data augmentation before scaling compute."

BAD (generic):
  "The CLI was refactored for better performance."
GOOD (specific):
  "Moving from single-pass to two-pass HTML generation (commit 2baf786) eliminated \
   context overflow — the builder now plans the narrative in Pass 1, then renders \
   each slide separately in Pass 2."

Every insight answers: what exactly happened, and what does it mean for what comes next?

══════════════════════
GIT HISTORY GUIDANCE
══════════════════════
- Commit messages are the factual record — quote them directly in headings and insights
- Frequent-change files are the core components — build slides around them
- Early commits = setup; middle commits = features; recent commits = fixes and polish
- Uncommitted changes = current state of work, highlight as "where we are now"

═══════════════════════════
VISION CONTEXT (if present)
═══════════════════════════
If a <VisionContext> block is provided, use those descriptions to write specific insights
for image and chart slides. Reference what the visual ACTUALLY SHOWS — concrete values,
trends, anomalies — NOT generic phrases like "see the chart" or "results shown above".
Example: "accuracy plateaued at 94.3% after epoch 28" beats "the training curve shows improvement".
"""


def _planner_user(project_name: str, description: str, domain: str,
                  files: list[ResultFile],
                  git_ctx_text: str | None = None,
                  delta: dict | None = None,
                  vision_descriptions: "dict[str, str] | None" = None) -> str:
    dc = _DOMAIN_CONFIG.get(domain, _DOMAIN_CONFIG["ml"])
    file_list = "\n".join(f"  - [{f.type}] {f.path}" for f in files)

    git_block = ""
    if git_ctx_text:
        git_block = f"\n<GitContext>\n{git_ctx_text}\n</GitContext>\n"

    delta_block = ""
    if delta and delta.get("prev_milestone"):
        new_f   = delta.get("new_files", [])
        mod_f   = delta.get("modified_files", [])
        commits = delta.get("commit_count", 0)
        days    = delta.get("days_elapsed", 0)
        prev_ms = delta.get("prev_milestone", "")
        curr_ms = delta.get("curr_milestone", "")
        prev_v  = delta.get("prev_version", "?")
        delta_block = (
            f"\n<VersionDelta>\n"
            f"This is version v{prev_v + 1} — a new versioned presentation since milestone \"{prev_ms}\".\n"
            f"Previous milestone: \"{prev_ms}\"\n"
            f"Current milestone:  \"{curr_ms}\"\n"
            f"Days elapsed: {days}\n"
            f"New files since last version: {len(new_f)} — {', '.join(new_f[:5])}\n"
            f"Modified files: {len(mod_f)} — {', '.join(mod_f[:5])}\n"
            f"Commits since last milestone: {commits}\n\n"
            f"INSTRUCTION: Slide 2 MUST be a 'recap' slide titled something like "
            f"\"Since v{prev_v}: What Changed\" that summarises the delta above — "
            f"new files added, commits made, days elapsed, and one sentence on what the team accomplished. "
            f"Use type: \"context\" with layout_hint \"\" for this slide.\n"
            f"</VersionDelta>\n"
        )

    vision_block = ""
    if vision_descriptions:
        lines = "\n".join(
            f"  {fname}: {desc}"
            for fname, desc in vision_descriptions.items()
            if not fname.startswith("/")  # deduplicate path vs filename entries
        )
        vision_block = f"\n<VisionContext>\n{lines}\n</VisionContext>\n"

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
        f"{git_block}"
        f"{delta_block}"
        f"{vision_block}\n"
        f"<ArtifactList>\n{file_list}\n</ArtifactList>\n\n"
        f"Generate the JSON outline now."
    )


# ── Pass 2: Coder prompt ──────────────────────────────────────────────────────

_CODER_SYSTEM = """\
You are a Reveal.js slide author. Write ONE <section> element for the slide described.

OUTPUT: Only the raw <section>...</section> HTML. No prose, no markdown, no explanation.

STRICT RULES:
1. Add data-auto-animate to every <section>.
2. Wrap every <li> in class="fragment".
3. USE THE EXACT HEADING from SlideSpec — never swap it for a generic label like "Results".
4. Speaker notes: 2-3 sentences referencing specific file names, function names, or commit details.
5. CODE slides: MAXIMUM 6 LINES. Cut everything else mercilessly. One subtitle sentence after.
6. Never invent facts not present in the SlideSpec or Artifacts.
7. No <style> tags. CSS vars available: --accent, --accent2, --fg, --dim
   Classes: r-fit-text, r-stretch, r-stack, fragment, subtitle, hero-metric

TEMPLATES BY TYPE — use the one matching the slide type:

code:
<section data-auto-animate>
  <h2>{EXACT HEADING FROM SPEC}</h2>
  <pre><code class="language-python" data-trim data-line-numbers>
{MAX 6 LINES of the most important code — nothing more}
  </code></pre>
  <p class="subtitle">{one sentence: why this design decision was made}</p>
  <aside class="notes">{2-3 specific sentences from the artifacts}</aside>
</section>

comparison:
<section data-auto-animate>
  <h2>{EXACT HEADING FROM SPEC}</h2>
  <div class="r-stack">
    <div class="fragment fade-out" style="width:100%;text-align:left">
      <p style="color:var(--dim);font-size:.7em;text-transform:uppercase">Before</p>
      <p>{specific before state from the artifacts}</p>
    </div>
    <div class="fragment" style="width:100%;text-align:left">
      <p style="color:var(--accent);font-size:.7em;text-transform:uppercase">After</p>
      <p>{specific after state — what improved}</p>
    </div>
  </div>
  <aside class="notes">{why this change was made, what the measured impact was}</aside>
</section>

table (for CSV data):
<section data-auto-animate>
  <h2>{EXACT HEADING FROM SPEC}</h2>
  <table style="width:100%;border-collapse:collapse;font-size:.75em">
    <thead><tr style="border-bottom:2px solid var(--accent)">
      <th style="padding:.4em .8em;text-align:left">{real col name}</th>
      <th style="padding:.4em .8em;text-align:left">{real col name}</th>
    </tr></thead>
    <tbody>
      <tr class="fragment"><td style="padding:.35em .8em">{real value}</td><td style="padding:.35em .8em">{real value}</td></tr>
    </tbody>
  </table>
  <p class="subtitle">{key insight: what pattern or outlier does this table show?}</p>
  <aside class="notes">{what action this data suggests}</aside>
</section>

general content (context, bullets, any other type):
<section data-auto-animate>
  <h2>{EXACT HEADING FROM SPEC}</h2>
  <ul>
    <li class="fragment">{specific insight — use the bullet_points from spec verbatim if provided}</li>
    <li class="fragment">{specific insight}</li>
    <li class="fragment">{specific insight}</li>
  </ul>
  <aside class="notes">{2-3 specific sentences}</aside>
</section>
"""


def _lookup_artifact(path: str, artifacts_map: dict) -> "ResultFile | None":
    rf = artifacts_map.get(path)
    if rf:
        return rf
    fname = path.rsplit("/", 1)[-1]
    return artifacts_map.get(fname)


def _coder_user(slide: dict, artifacts_map: dict[str, ResultFile]) -> str:
    artifact_blocks = []
    for path in slide.get("artifacts", []):
        rf = _lookup_artifact(path, artifacts_map)
        if rf is None:
            continue
        if rf.type in ("image", "svg"):
            # Pass ready-to-use <img> tag so model just copies it
            artifact_blocks.append(
                f"[IMAGE: {rf.filename}]\n"
                f'<img class="r-stretch" src="{rf.content}" alt="{rf.filename}">'
            )
        elif rf.type == "data":
            artifact_blocks.append(
                f"[DATA: {rf.filename}]\n{rf.content[:1500]}"
                + ("\n...(truncated)" if len(rf.content) > 1500 else "")
            )
        elif rf.type in ("text", "code"):
            # Hard-truncate code to enforce the 6-line rule downstream
            max_chars = 350 if rf.type == "code" else 1200
            artifact_blocks.append(
                f"[{rf.type.upper()}: {rf.filename}]\n{rf.content[:max_chars]}"
                + ("\n...(truncated — use only the key lines shown above)"
                   if len(rf.content) > max_chars else "")
            )

    artifacts_text = "\n\n".join(artifact_blocks) if artifact_blocks else "(no artifacts)"

    bullets_text = ""
    if slide.get("bullet_points"):
        bullets_text = (
            "bullet_points (use these verbatim as <li> content):\n"
            + "\n".join(f"  - {b}" for b in slide["bullet_points"])
            + "\n"
        )

    return (
        f"<SlideSpec>\n"
        f"type: {slide['type']}\n"
        f"heading: {slide['heading']}\n"
        f"insight: {slide.get('insight', '')}\n"
        + bullets_text
        + f"speaker_notes: {slide.get('speaker_notes', '')}\n"
        f"</SlideSpec>\n\n"
        f"<Artifacts>\n{artifacts_text}\n</Artifacts>\n\n"
        f"Write the <section> HTML for this {slide['type']} slide."
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

    # Strip markdown fence
    fence = re.search(r"```(?:json)?\s*(\{.*)", text, re.DOTALL | re.IGNORECASE)
    if fence:
        inner = fence.group(1)
        closing = inner.rfind("```")
        if closing != -1:
            inner = inner[:closing]
        text = inner.strip()

    # Isolate the outermost { ... }
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]

    # Try strict parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Clean up common LLM slop and retry:
    # 1. strip // line comments
    text = re.sub(r"//[^\n]*", "", text)
    # 2. strip /* block comments */
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # 3. remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 4. if JSON is truncated, close open structures so we get partial data
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Count unclosed braces/brackets and close them
        depth_brace  = text.count("{") - text.count("}")
        depth_bracket = text.count("[") - text.count("]")
        # Remove any trailing incomplete string or value
        text = re.sub(r',?\s*"[^"]*$', "", text)
        text = re.sub(r',?\s*\w+\s*$',  "", text)
        text += "]" * max(depth_bracket, 0) + "}" * max(depth_brace, 0)
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
    delta: dict | None = None,
    cloud_api_url: str = "",
    cloud_api_key: str = "",
    image_gen_model: str = "",
    image_gen_enabled: bool = False,
) -> dict:
    import time
    from rich.console import Console
    from rich.table import Table
    from rich import box as rbox

    console = Console()

    # ── Init ──────────────────────────────────────────────────────────────────
    global _cloud_config
    _cloud_config = {"cloud_api_url": cloud_api_url, "cloud_api_key": cloud_api_key}

    _planner = planner_model or model
    _coder   = coder_model   or model
    _vision  = vision_model  or model
    _fast    = fast_model    or _coder

    using_cloud = bool(cloud_api_url and cloud_api_key)
    domain = domain_override or detect_domain(description, files)

    console.print()
    if using_cloud:
        console.print(f"[dim][sarathi][/dim] Backend: [cyan]cloud[/cyan] ({cloud_api_url})")
    console.print(f"[dim][sarathi][/dim] Domain: [cyan]{domain}[/cyan]")
    console.print()

    # ── Ollama warmup (local only) ─────────────────────────────────────────────
    if not using_cloud and not fast:
        unique_models = list(dict.fromkeys([_planner, _coder] +
                                           ([_vision] if _vision != _planner else [])))
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
        try:
            import ollama as _ollama
            _ps = _ollama.ps()
            already_loaded = {getattr(mm, "model", "") for mm in (getattr(_ps, "models", []) or [])}
        except Exception:
            already_loaded = set()
        for m in unique_models:
            role = role_map.get(m, "Model")
            if m in already_loaded:
                load_table.add_row(role, m, "[green]✓ in RAM[/green]", "[dim]—[/dim]")
                continue
            console.print(f"  [dim]Loading {m}...[/dim]", end="\r")
            t0 = time.perf_counter()
            try:
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                    fut = _ex.submit(_ollama.generate, model=m, prompt="hi",
                                     options={"num_predict": 1})
                    try:
                        fut.result(timeout=90)
                        load_table.add_row(role, m, "[green]✓ loaded[/green]",
                                           f"[dim]{time.perf_counter()-t0:.1f}s[/dim]")
                    except _cf.TimeoutError:
                        load_table.add_row(role, m, "[yellow]⚠ slow (CPU?)[/yellow]",
                                           f"[dim]{time.perf_counter()-t0:.0f}s+[/dim]")
            except Exception as exc:
                load_table.add_row(role, m, "[red]✗ error[/red]",
                                   f"[dim]{str(exc)[:30]}[/dim]")
        console.print()
        console.print(load_table)
        console.print()

    # ── Fast mode (single-pass, skip agentic pipeline) ────────────────────────
    if fast:
        console.print(f"[dim][sarathi][/dim] Fast mode — single-pass ([bold]{_fast}[/bold])...")
        all_files = _trim_context(files, max_chars=12000, max_files=10)
        t_gen = time.perf_counter()
        html_doc = _generate_single_pass(
            project_name, description, domain, all_files, _fast,
            theme, git_ctx_text, verbose=verbose, delta=delta,
        )
        duration_s = time.perf_counter() - t_gen
        output_html.write_text(html_doc, encoding="utf-8")
        console.print("[green][sarathi][/green] Presentation ready (single-pass).")
        return {
            "tok_s": _last_gen_tps,
            "duration_s": round(duration_s, 1),
            "slide_count": html_doc.count("<section"),
            "mode": "fast",
        }

    # ═════════════════════════════════════════════════════
    # AGENTIC PIPELINE  Stage 0 → 1 → 2 → 3 → 4
    # ═════════════════════════════════════════════════════

    console.print("[bold][sarathi] Agentic pipeline starting...[/bold]")
    console.print()

    # Stage 0 — Chart Agent
    console.print("[dim][sarathi] Stage 0 — Chart Agent[/dim]")
    viz_files = _chart_agent(files, project_dir, console)
    all_files = files + viz_files

    if len(all_files) > 12 or sum(len(f.content) for f in all_files) > 20000:
        all_files = _trim_context(all_files, max_chars=15000, max_files=12)
        console.print(f"  [dim]Trimmed to {len(all_files)} most relevant file(s)[/dim]")

    artifacts_map = _build_artifacts_map(all_files)
    console.print()

    # Stage 1 — Vision Agent
    console.print("[dim][sarathi] Stage 1 — Vision Agent[/dim]")
    vision_descriptions: dict[str, str] = {}
    if _vision:
        vision_descriptions = _vision_agent(all_files, _vision, console, verbose)
    if not vision_descriptions:
        console.print("  [dim]Vision Agent: no images to analyse[/dim]")
    console.print()

    # Stage 2 — Planner Agent
    console.print("[dim][sarathi] Stage 2 — Planner Agent[/dim]")
    if outline_path and outline_path.exists():
        console.print(f"  Loading outline from {outline_path.name}...")
        outline = json.loads(outline_path.read_text(encoding="utf-8"))
    else:
        console.print(f"  Model: [bold]{_planner}[/bold]")
        outline = _generate_outline(
            project_name, description, domain, all_files, _planner, git_ctx_text,
            verbose=verbose, delta=delta, vision_descriptions=vision_descriptions or None,
        )
        n_slides = len(outline.get("slides", []))
        title    = outline.get("title", project_name)
        console.print(
            f"  [green]✓ Outline ready:[/green] [bold]{title}[/bold] — {n_slides} slides"
        )
        if outline_path:
            outline_path.parent.mkdir(parents=True, exist_ok=True)
            outline_path.write_text(json.dumps(outline, indent=2), encoding="utf-8")
            return {}
    console.print()

    # Stage 3 — Image Gen Agent (optional)
    console.print("[dim][sarathi] Stage 3 — Image Gen Agent[/dim]")
    if image_gen_enabled and image_gen_model and using_cloud:
        new_arts = _image_gen_agent(
            outline, artifacts_map, image_gen_model,
            cloud_api_url, cloud_api_key, console,
        )
        artifacts_map.update(new_arts)
    else:
        console.print("  [dim]Image Gen: disabled (enable in setup or with image_gen_enabled=True)[/dim]")
    console.print()

    # Stage 4 — Coder Agent
    console.print("[dim][sarathi] Stage 4 — Coder Agent[/dim]")
    console.print(f"  Model: [bold]{_coder}[/bold]")
    slides = outline.get("slides", [])
    slides_html: list[str] = []
    n = len(slides)
    t_gen = time.perf_counter()

    for i, slide in enumerate(slides, 1):
        heading = slide.get("heading", f"Slide {slide.get('id', '')}")
        console.print(f"  Slide {i}/{n} — [bold]{heading[:60]}[/bold]")
        try:
            html = _render_slide(slide, artifacts_map, _coder, verbose=verbose)
        except Exception as exc:
            html = (
                f"<section><h2>{heading}</h2>"
                f"<p style='color:#f48fb1'>Render error: {exc}</p></section>"
            )
        slides_html.append(html)

    duration_s = time.perf_counter() - t_gen
    console.print(f"  [green]✓ All {len(slides_html)} slides rendered.[/green]")
    console.print()

    # ── Assemble ───────────────────────────────────────────────────────────────
    html_doc = _assemble(outline.get("title", project_name), slides_html, theme)
    output_html.write_text(html_doc, encoding="utf-8")

    for s in outline.get("slides", []):
        s["_theme"] = theme
    try:
        from . import pptx_exporter
        pptx_exporter.to_pptx(outline, artifacts_map, output_html.with_suffix(".pptx"))
    except Exception:
        pass

    console.print(f"[green][sarathi] Presentation ready →[/green] {output_html}")
    return {
        "tok_s":       _last_gen_tps,
        "duration_s":  round(duration_s, 1),
        "slide_count": len(slides_html),
        "mode":        "agentic",
    }


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
    delta: dict | None = None,
) -> str:
    """Generate slides in one LLM call, then wrap with our guaranteed-correct HTML shell.

    Ask for <section> elements only — never ask the model to generate the full HTML
    boilerplate (CDN, scripts, theme) because it always gets it wrong.
    """
    dc = _DOMAIN_CONFIG.get(domain, _DOMAIN_CONFIG["ml"])

    file_parts: list[str] = []
    for rf in files:
        if rf.type in ("image", "svg"):
            file_parts.append(
                f"[IMAGE: {rf.filename}] — embed as: "
                f"<img class=\"r-stretch\" src=\"{rf.content[:80]}...\">"
            )
        elif rf.type == "data":
            file_parts.append(f"[DATA: {rf.filename}]\n{rf.content[:1200]}")
        else:
            file_parts.append(f"[{rf.type.upper()}: {rf.filename}]\n{rf.content[:800]}")

    git_block = f"<GitContext>\n{git_ctx_text}\n</GitContext>\n\n" if git_ctx_text else ""

    delta_block = ""
    if delta and delta.get("prev_milestone"):
        new_f   = delta.get("new_files", [])
        mod_f   = delta.get("modified_files", [])
        commits = delta.get("commit_count", 0)
        days    = delta.get("days_elapsed", 0)
        prev_ms = delta.get("prev_milestone", "")
        prev_v  = delta.get("prev_version", "?")
        delta_block = (
            f"<VersionDelta>\n"
            f"This is version v{prev_v + 1} — a new presentation since milestone \"{prev_ms}\".\n"
            f"New files: {len(new_f)} ({', '.join(new_f[:4])})\n"
            f"Modified: {len(mod_f)} files\n"
            f"Commits since last milestone: {commits} over {days} days\n"
            f"INSTRUCTION: Slide 2 must be a recap titled \"Since v{prev_v}: What Changed\" "
            f"summarising the delta above in 3 bullets.\n"
            f"</VersionDelta>\n\n"
        )

    system = f"""\
You are an expert Reveal.js presentation author. Generate 7-9 <section> elements that \
tell the real story of this project.

OUTPUT FORMAT: Only raw <section>...</section> blocks. No <!DOCTYPE>, no <html>, \
no <head>, no <script>, no <style> tags. Nothing else.

━━━━━━━━━━━━━━━━━━━━━━━━
GROUNDING RULE — CRITICAL
━━━━━━━━━━━━━━━━━━━━━━━━
Every word on every slide must come from the files and git history provided below.
NEVER write placeholder text like "Note about this slide", "[version number]", or \
"https://example.com". NEVER invent metrics or outcomes not in the files.
If you don't find a specific fact, don't include it. Use only what you can see.

━━━━━━━━━━━━━━━━━━━━━━━━
NARRATIVE ARC ({domain.upper()})
━━━━━━━━━━━━━━━━━━━━━━━━
{dc['arc']}
Slide order: {dc['arc_order']}
Tone: {dc['tone']}

━━━━━━━━━━━━━━━━━━━━━━
REQUIRED SLIDE STRUCTURE
━━━━━━━━━━━━━━━━━━━━━━
Slide 1 — TITLE:
<section data-auto-animate>
  <h1>{{project name}}</h1>
  <p class="subtitle">{{real one-liner from description or README}}</p>
  <p class="subtitle" style="margin-top:1.5em;font-size:.55em;color:var(--dim)">May 2026</p>
  <aside class="notes">{{what this project is, who built it, why it matters — from the files}}</aside>
</section>

Slide 2 — CONTEXT (the real problem):
<section data-auto-animate>
  <h2>{{the actual problem this project solves}}</h2>
  <ul>
    <li class="fragment">{{real pain point from README or CLAUDE.md}}</li>
    <li class="fragment">{{real constraint or gap in existing tools}}</li>
    <li class="fragment">{{what Sarathi/this project does differently}}</li>
  </ul>
  <aside class="notes">{{expand on why this problem matters, what alternatives exist}}</aside>
</section>

Middle slides — patterns by content type:

  SCREENSHOT/IMAGE — if image files are provided, dedicate a full slide:
  <section data-auto-animate>
    <h2>{{what the screenshot shows — not "Screenshot" as a label}}</h2>
    <img class="r-stretch" src="{{FULL DATA URI}}" alt="{{description}}">
    <p style="font-size:.5em;color:var(--dim)">{{one annotation pointing to the key thing}}</p>
    <aside class="notes">{{walk through what the viewer is seeing}}</aside>
  </section>

  PLOT/CHART — for data visualisations, same pattern as screenshot but with insight heading:
  <section data-auto-animate>
    <h2>{{conclusion drawn from the chart — the "so what"}}</h2>
    <img class="r-stretch" src="{{chart data URI}}" alt="{{chart description}}">
    <aside class="notes">{{explain the trend, outlier, or key data point}}</aside>
  </section>

  CODE: heading=what the code does, pre/code block 10-20 lines, subtitle=why this design
  FEATURE/CAPABILITY: heading=conclusion, bullets=fragment li, notes=specific detail
  ARCHITECTURE: heading=the key design decision, bullets=components and their roles

  METRIC CALLOUT — if there's a standout number, give it its own slide:
  <section data-auto-animate>
    <p style="color:var(--accent);font-size:.6em;text-transform:uppercase;letter-spacing:.1em">KEY RESULT</p>
    <h2 class="r-fit-text hero-metric">{{the actual number}}</h2>
    <p class="subtitle">{{what it means}}</p>
    <aside class="notes">{{context: what changed to achieve this, why this level matters}}</aside>
  </section>

Second-to-last — TAKEAWAYS:
<section data-auto-animate>
  <h2>Key Takeaways</h2>
  <ul>
    <li class="fragment">{{specific insight with real detail from project}}</li>
    <li class="fragment">{{specific insight with real detail from project}}</li>
    <li class="fragment">{{specific insight with real detail from project}}</li>
  </ul>
  <aside class="notes">{{what the audience should remember in one week}}</aside>
</section>

Last — NEXT STEPS:
<section data-auto-animate>
  <h2>What Comes Next</h2>
  <ul>
    <li class="fragment">{{concrete next action visible from the current codebase}}</li>
    <li class="fragment">{{open question or known limitation}}</li>
    <li class="fragment">{{longer-term vision}}</li>
  </ul>
  <aside class="notes">{{why these priorities, what would unblock the most value}}</aside>
</section>

  TABLE — for CSV data (max 8 rows, real column names and values from the file):
  <section data-auto-animate>
    <h2>{{insight: what this data reveals — the key pattern or outlier}}</h2>
    <table style="width:100%;border-collapse:collapse;font-size:.75em">
      <thead><tr style="border-bottom:2px solid var(--accent)">
        <th style="padding:.4em .8em;text-align:left">{{col1}}</th>
        <th style="padding:.4em .8em;text-align:left">{{col2}}</th>
      </tr></thead>
      <tbody>
        <tr class="fragment"><td style="padding:.35em .8em">{{real val}}</td><td style="padding:.35em .8em">{{real val}}</td></tr>
      </tbody>
    </table>
    <p class="subtitle">{{one sentence annotation on the key row/pattern}}</p>
    <aside class="notes">{{walk the audience through the most important row or trend}}</aside>
  </section>

━━━━━━━━
RULES
━━━━━━━━
- data-auto-animate on every <section>
- class="fragment" on every <li>
- Headings are conclusions: "sarathi Cuts Slide Prep from Hours to Minutes" not "Features"
- Speaker notes are specific: reference real file names, commit hashes, function names
- No invented URLs, no placeholder brackets, no lorem ipsum
- CSS vars available: --accent (#4fc3f7), --accent2 (#f48fb1), --fg, --fg2, --dim, --bg
- CSS classes: r-fit-text, r-stretch, r-stack, fragment, fade-out, subtitle, hero-metric
- VISUAL FIRST: if image/chart files are provided, EMBED them with <img class="r-stretch" src="FULL_DATA_URI">
- ANTI-CODE-DUMP: never fill a slide with an entire code file. Max 8 lines, most important only.
- VARIETY: at least 3 different slide types across the deck. A deck of all bullet slides is a failure.
- CSV DATA: if CSV files are provided, show a TABLE slide or METRIC CALLOUT — not a code block.
"""

    user = (
        f"{git_block}"
        f"{delta_block}"
        f"Project: {project_name}\nDescription: {description}\n\n"
        "Files (read carefully — your slides must reference this content):\n\n"
        + "\n\n---\n\n".join(file_parts) +
        "\n\nNow generate the <section> slides. Only output raw <section>...</section> blocks."
    )

    text = _chat(model, system, user, verbose=verbose)

    # Extract all <section> blocks from the response
    sections = re.findall(r"<section[\s\S]*?</section>", text, re.IGNORECASE)

    if sections:
        return _assemble(project_name, sections, theme)

    # Fallback: model returned something — wrap it
    cleaned = re.sub(r"```[a-z]*\n?|```", "", text).strip()
    if cleaned:
        return _assemble(project_name,
                         [f"<section><h2>{project_name}</h2><p>{cleaned[:800]}</p></section>"],
                         theme)
    return _assemble(project_name,
                     [f"<section><h2>{project_name}</h2><p>{description}</p></section>"],
                     theme)


_OLLAMA_BASE = "http://localhost:11434"
_OLLAMA_KEY  = "ollama"




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
        max_tokens=8192,
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
    """Stream generation via Ollama's native Python SDK."""
    import ollama as _ollama
    import time
    from rich.console import Console as _C
    from rich.progress import (
        Progress, BarColumn, TextColumn, SpinnerColumn, TimeElapsedColumn
    )

    _con = _C()

    if verbose:
        from rich.rule import Rule
        _con.print(Rule("[bold cyan]PROMPT → SYSTEM[/bold cyan]", style="cyan"))
        _con.print(system[:3000] + ("..." if len(system) > 3000 else ""))
        _con.print(Rule("[bold cyan]PROMPT → USER[/bold cyan]", style="cyan"))
        _con.print(user[:3000] + ("..." if len(user) > 3000 else ""))

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]

    chunks: list[str] = []
    out_tokens  = 0
    eval_tokens = 0
    est_in      = (len(system) + len(user)) // 4
    t0          = None   # starts on first output token, not on request

    with Progress(
        SpinnerColumn(),
        BarColumn(bar_width=36),
        TextColumn("[dim]{task.description}[/dim]"),
        TimeElapsedColumn(),
        console=_con,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"in ~{est_in:,}  out 0  ·  — tok/s",
            total=None,
        )

        for chunk in _ollama.chat(model=model, messages=messages, stream=True):
            text = chunk.get("message", {}).get("content", "")
            if text:
                if t0 is None:
                    t0 = time.perf_counter()   # start timer on first output token
                chunks.append(text)
                out_tokens += 1

            # Ollama reports accurate counts in the final chunk
            if chunk.get("done"):
                eval_tokens = chunk.get("eval_count", out_tokens)
                eval_dur    = chunk.get("eval_duration", 0)   # ns — pure generation time
                tps         = eval_tokens / (eval_dur / 1e9) if eval_dur else 0
            else:
                elapsed = time.perf_counter() - t0 if t0 else 0
                tps     = out_tokens / max(elapsed, 0.1) if elapsed else 0

            progress.update(
                task,
                description=(
                    f"in ~{est_in:,}  out {out_tokens}"
                    + (f"  ·  {tps:.1f} tok/s" if tps else "  ·  loading...")
                ),
            )

    # Final accurate numbers from Ollama (eval_duration = pure generation time)
    final_tokens = eval_tokens or out_tokens
    elapsed      = time.perf_counter() - t0 if t0 else 0
    final_tps    = eval_tokens / (elapsed) if (eval_tokens and elapsed) else 0
    _con.print(
        f"  [green]✓[/green]  "
        f"in [dim]~{est_in:,}[/dim]  ·  "
        f"out [bold]{final_tokens}[/bold]  ·  "
        f"[bold]{final_tps:.1f} tok/s[/bold]  ·  {elapsed:.0f}s"
    )

    # Expose tps so generate() can include it in returned stats
    global _last_gen_tps
    _last_gen_tps = final_tps

    result = "".join(chunks)

    if verbose:
        from rich.rule import Rule
        from rich.panel import Panel
        _con.print(Rule("[bold green]RESPONSE[/bold green]", style="green"))
        _con.print(Panel(result[:4000] + ("..." if len(result) > 4000 else ""),
                         border_style="green", expand=False))

    return result


def _chat_via_openai(model: str, system: str, user: str, verbose: bool = False) -> str:
    """Stream generation via an OpenAI-compatible API (LiteLLM, Azure, etc.)."""
    from openai import OpenAI
    import time
    import sys

    url = _cloud_config["cloud_api_url"]
    raw_key = _cloud_config["cloud_api_key"]
    # Decrypt key if it was stored encrypted
    from . import keystore as _ks
    key = _ks.decrypt(raw_key)

    client = OpenAI(api_key=key, base_url=url)

    if verbose:
        from rich.console import Console as _C
        _C().print(f"  [dim][cloud] {url} · model={model}[/dim]")

    est_in = (len(system) + len(user)) // 4
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]

    # Retry with backoff on rate-limit (429) or transient server errors (5xx)
    _MAX_RETRIES = 3
    for attempt in range(_MAX_RETRIES):
        try:
            chunks: list[str] = []
            out_tokens = 0
            t0 = time.perf_counter()

            stream = client.chat.completions.create(
                model=model, messages=messages, stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    chunks.append(delta.content)
                    out_tokens += 1
                    if out_tokens % 10 == 0:
                        elapsed = time.perf_counter() - t0
                        tps = out_tokens / max(elapsed, 0.1)
                        bar_full = min(out_tokens // 20, 30)
                        bar = "█" * bar_full + "░" * (30 - bar_full)
                        sys.stdout.write(
                            f"\r  [{bar}]  out {out_tokens}  {tps:.1f} tok/s  {elapsed:.0f}s" + " " * 20
                        )
                        sys.stdout.flush()

            elapsed = time.perf_counter() - t0
            tps = out_tokens / max(elapsed, 0.001)
            sys.stdout.write("\r" + " " * 100 + "\r")
            sys.stdout.flush()
            print(f"  ✓  ~{est_in:,} in  ·  {out_tokens} out  ·  {tps:.1f} tok/s  ·  {elapsed:.0f}s")

            global _last_gen_tps
            _last_gen_tps = tps
            return "".join(chunks)

        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
            is_rate_limit = status == 429 or "rate" in str(exc).lower()
            is_server_err = status and status >= 500

            if (is_rate_limit or is_server_err) and attempt < _MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s
                sys.stdout.write("\r" + " " * 100 + "\r")
                sys.stdout.flush()
                from rich.console import Console as _C
                _C().print(
                    f"  [yellow]⚠ Rate limit / server error (attempt {attempt+1}/{_MAX_RETRIES}) "
                    f"— retrying in {wait}s...[/yellow]"
                )
                time.sleep(wait)
            else:
                raise


def _chat(model: str, system: str, user: str, verbose: bool = False) -> str:
    if _cloud_config.get("cloud_api_url") and _cloud_config.get("cloud_api_key"):
        try:
            return _chat_via_openai(model, system, user, verbose=verbose)
        except Exception as exc:
            from rich.console import Console as _C
            _C().print(
                f"  [yellow]⚠ Cloud API error ({exc.__class__.__name__}: {exc}) "
                f"— falling back to Ollama[/yellow]"
            )
    return _chat_via_ollama(model, system, user, verbose=verbose)


# ── Agent helpers ─────────────────────────────────────────────────────────────

def _build_artifacts_map(files: "list[ResultFile]") -> "dict[str, ResultFile]":
    """Build lookup dict by both full path and filename."""
    m: dict = {}
    for rf in files:
        m[rf.path]     = rf
        m[rf.filename] = rf
    return m


_VISION_SYSTEM = """\
You are a visual analyst. Describe this image or chart in 2-3 sentences.
Focus on: (1) what it shows, (2) the key trend or finding, (3) what it means for the project.
Be specific — name actual values, axis labels, or categories if visible.
Output only the description. No preamble, no markdown.
"""


def _vision_agent(
    files: "list[ResultFile]",
    model: str,
    console,
    verbose: bool = False,
) -> "dict[str, str]":
    """Run vision model on image/chart artifacts. Returns path→description dict."""
    candidates = [
        rf for rf in files
        if rf.type in ("image", "svg") and rf.content.startswith("data:")
    ][:5]  # cap at 5 to limit latency

    if not candidates:
        return {}

    console.print(
        f"  [dim]Vision Agent:[/dim] analysing {len(candidates)} image(s)..."
    )
    descriptions: dict[str, str] = {}

    for rf in candidates:
        user_msg = (
            f"Image file: {rf.filename}\n\n"
            f"[Image data URI — embedded below]\n{rf.content[:200]}...\n\n"
            "Describe this image/chart in 2-3 sentences."
        )
        try:
            desc = _chat(model, _VISION_SYSTEM, user_msg, verbose=verbose).strip()
            if desc:
                descriptions[rf.path]     = desc
                descriptions[rf.filename] = desc
        except Exception:
            pass  # vision silently skipped if model can't process images

    if descriptions:
        console.print(
            f"  [green]✓ Vision Agent:[/green] "
            f"{len(candidates)} image(s) described"
        )
    return descriptions


def _chart_agent(
    files: "list[ResultFile]",
    project_dir: "Path",
    console,
) -> "list[ResultFile]":
    """Pre-render CSVs to matplotlib charts. Thin wrapper around viz.process()."""
    from . import viz as viz_module

    csv_count = sum(
        1 for f in files if f.type == "data" and f.filename.endswith(".csv")
    )
    if csv_count:
        console.print(
            f"  [dim]Chart Agent:[/dim] rendering {csv_count} CSV(s) → matplotlib charts"
        )

    charts = viz_module.process(files, project_dir)

    if charts:
        console.print(
            f"  [green]✓ Chart Agent:[/green] {len(charts)} chart(s) ready"
        )
    return charts


def _image_gen_agent(
    outline: dict,
    artifacts_map: "dict[str, ResultFile]",
    image_gen_model: str,
    cloud_api_url: str,
    cloud_api_key: str,
    console,
) -> "dict[str, ResultFile]":
    """Generate AI images for slides that lack visual artifacts (FLUX/DALL-E)."""
    if not (image_gen_model and cloud_api_url and cloud_api_key):
        return {}

    from openai import OpenAI
    from . import keystore as _ks

    client = OpenAI(api_key=_ks.decrypt(cloud_api_key), base_url=cloud_api_url)

    # Identify slides that want an image but have no matching artifact
    candidates = []
    for slide in outline.get("slides", []):
        if slide.get("type") not in ("image", "chart"):
            continue
        has = any(
            _lookup_artifact(a, artifacts_map)
            for a in slide.get("artifacts", [])
        )
        if not has:
            candidates.append(slide)

    candidates = candidates[:3]  # max 3 to keep latency sane
    if not candidates:
        return {}

    console.print(
        f"  [dim]Image Gen Agent:[/dim] generating {len(candidates)} image(s) via {image_gen_model}"
    )
    new_artifacts: dict[str, ResultFile] = {}

    for slide in candidates:
        prompt = (
            f"Technical illustration: {slide['heading']}. "
            f"{slide.get('insight', '')[:200]}. "
            "Clean minimal style, dark background, professional presentation graphic."
        )
        try:
            resp = client.images.generate(
                model=image_gen_model,
                prompt=prompt,
                size="512x512",
                response_format="b64_json",
                n=1,
            )
            b64  = resp.data[0].b64_json
            data_uri = f"data:image/png;base64,{b64}"
            key  = f"_generated_slide_{slide['id']}"
            rf   = ResultFile(path=key, filename=f"{key}.png",
                              type="image", content=data_uri)
            new_artifacts[key] = rf
            slide.setdefault("artifacts", []).insert(0, key)
            console.print(
                f"  [green]✓ Image Gen:[/green] slide {slide['id']} — "
                f"{slide['heading'][:50]}"
            )
        except Exception as exc:
            console.print(
                f"  [yellow]⚠ Image Gen:[/yellow] slide {slide['id']} failed "
                f"({exc.__class__.__name__})"
            )

    return new_artifacts


def _generate_outline(
    project_name: str,
    description: str,
    domain: str,
    files: list[ResultFile],
    model: str,
    git_ctx_text: str | None = None,
    verbose: bool = False,
    delta: dict | None = None,
    vision_descriptions: "dict[str, str] | None" = None,
) -> dict:
    user_msg = _planner_user(
        project_name, description, domain, files, git_ctx_text,
        delta=delta, vision_descriptions=vision_descriptions,
    )
    text = _chat(model, _PLANNER_SYSTEM, user_msg, verbose=verbose)
    return _extract_json(text)


def _render_slide_nollm(slide: dict, artifacts_map: dict) -> "str | None":
    """Render simple slide types directly in Python — fast, reliable, no LLM tokens wasted."""
    stype  = slide.get("type", "")
    heading = slide.get("heading", "Slide")
    insight = slide.get("insight", "")
    notes   = slide.get("speaker_notes", "") or insight
    bullets = slide.get("bullet_points", [])

    # Title slide
    if stype == "title":
        from datetime import date
        month_year = date.today().strftime("%B %Y")
        sub = insight[:200] if insight else ""
        return (
            '<section data-auto-animate>\n'
            f'  <h1>{heading}</h1>\n'
            + (f'  <p class="subtitle">{sub}</p>\n' if sub else "")
            + f'  <p class="subtitle" style="margin-top:1.5em;font-size:.55em;color:var(--dim)">{month_year}</p>\n'
            f'  <aside class="notes">{notes}</aside>\n'
            '</section>'
        )

    # Image / Chart — embed the full data URI directly, no LLM needed
    if stype in ("image", "chart"):
        for path in slide.get("artifacts", []):
            rf = _lookup_artifact(path, artifacts_map)
            if rf and rf.type in ("image", "svg"):
                ann = insight[:200] if insight else ""
                return (
                    '<section data-auto-animate>\n'
                    f'  <h2>{heading}</h2>\n'
                    f'  <img class="r-stretch" src="{rf.content}" alt="{rf.filename}">\n'
                    + (f'  <p style="font-size:.5em;color:var(--dim)">{ann}</p>\n' if ann else "")
                    + f'  <aside class="notes">{notes}</aside>\n'
                    '</section>'
                )
        return None  # no image artifact found — fall back to LLM

    # Metric callout — extract the first number+unit from heading or insight
    if stype == "metric_callout":
        m = re.search(
            r'(\d[\d,\.]*\s*(?:%|x|×|ms|s(?= )|MB|GB|K\b|M\b|B\b)?)',
            heading + " " + insight
        )
        if m:
            metric = m.group(1).strip()
            sub = insight[:200] if insight else heading
            return (
                '<section data-auto-animate>\n'
                '  <p style="color:var(--accent);font-size:.65em;text-transform:uppercase;'
                'letter-spacing:.12em;margin-bottom:.3em">KEY RESULT</p>\n'
                f'  <h2 class="r-fit-text hero-metric">{metric}</h2>\n'
                f'  <p class="subtitle">{sub}</p>\n'
                f'  <aside class="notes">{notes}</aside>\n'
                '</section>'
            )
        return None  # no metric found — fall back to LLM

    # Bullet slides — use the planner's bullet_points directly (already grounded in artifacts)
    if stype in ("context", "takeaways", "next_steps") and bullets:
        items = "\n".join(f'    <li class="fragment">{b}</li>' for b in bullets[:5])
        return (
            '<section data-auto-animate>\n'
            f'  <h2>{heading}</h2>\n'
            '  <ul>\n'
            f'{items}\n'
            '  </ul>\n'
            f'  <aside class="notes">{notes}</aside>\n'
            '</section>'
        )

    return None  # code, comparison, table, and unplanned bullets go to LLM


def _render_slide(
    slide: dict,
    artifacts_map: dict[str, ResultFile],
    model: str,
    verbose: bool = False,
) -> str:
    # Fast path: Python rendering for reliable slide types (no LLM tokens)
    html = _render_slide_nollm(slide, artifacts_map)
    if html is not None:
        return html
    # LLM path: code, comparison, table, or bullet slides without planned points
    user_msg = _coder_user(slide, artifacts_map)
    text = _chat(model, _CODER_SYSTEM, user_msg, verbose=verbose)
    return _extract_section(text)
