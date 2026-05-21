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
      "type": "title | context | metric_callout | chart | image | code | comparison | takeaways | next_steps | feature_grid | timeline | table | section_divider | statement",
      "heading": "A conclusion drawn from real evidence — not a label like 'Results'",
      "artifacts": ["exact/path/from/artifact/list"],
      "insight": "2-3 sentences grounded in real content. WHAT does this slide show from the actual files? WHY does it matter for this project specifically?",
      "speaker_notes": "3-4 sentences that expand on the slide. Reference specific details from the files. What should the presenter emphasize?",
      "layout_hint": "r-fit-text | r-stretch | r-stack | auto-animate | (empty)",
      "bullet_points": ["3-5 specific, complete bullets — each references real content"],
      "visual_type": "none | existing_file | python_chart | ai_image",
      "visual_prompt": "Exact generation instruction — see VISUAL STRATEGY section. Empty string if visual_type is none or existing_file."
    }
  ]
}

════════════════════════════════════════
VISUAL STRATEGY — SET FOR EVERY SLIDE
════════════════════════════════════
Every slide needs a visual_type decision. Think of it as choosing the right visual medium:

visual_type options:
  none          → no image needed. Use for: bullets, comparison, code, metric callout, timeline, section_divider, statement.
  existing_file → an image/chart/screenshot already exists in the artifact list. List the path in artifacts[].
  python_chart  → generate a matplotlib chart from REAL DATA in the project files.
                  Use when: CSV rows exist, specific metrics are mentioned, before/after numbers are present.
  ai_image      → generate a conceptual AI image. Use ONLY for architecture diagrams, system flows,
                  abstract concepts that have no data backing. MAX 2 per deck.

Decision tree — pick the FIRST matching rule:
  1. Artifact list has an image/chart file for this slide → existing_file
  2. Slide has numeric data in CSVs/files that a chart would clarify → python_chart
  3. Slide needs an architecture/flow/concept diagram not in files → ai_image
  4. Everything else → none

visual_prompt rules (REQUIRED for python_chart and ai_image, empty for others):

  python_chart — must be a precise chart specification:
    "Chart type: bar | line | scatter | heatmap | hbar | pie
     X-axis: [label]. Y-axis: [label] (unit).
     Data: [actual values from files — name every data point].
     Highlight: [which bar/line to emphasize and why].
     Title: '[exact title string]'."

    GOOD: "Chart type: hbar. Y-axis: ['Before (Q1)', 'After (Q2)']. X-axis: P99 Latency (ms).
           Data: Q1=840, Q2=47. Highlight Q2 bar in accent color. Title: 'Latency: 94% Reduction'."
    BAD:  "bar chart of latency improvements"

  ai_image — must describe exact visual elements, layout, and relationships:
    "Style: [clean technical | minimal flat | isometric].
     Elements: [list every box/arrow/icon and its label].
     Layout: [left-to-right | top-to-bottom | radial].
     NO decorative gradients, NO text inside shapes."

    GOOD: "Style: clean technical diagram. Elements: three labeled boxes in a row —
           'Producer (ML Model)' → arrow labeled '12× throughput' → 'Kafka' → arrow → 'Consumer (Sarathi)'.
           Layout: left-to-right. Dark background."
    BAD:  "system architecture diagram"

══════════════════
SLIDE COUNT & ORDERING
══════════════════════
- 10 to 14 slides total
- Slide 1: title — project name + one real sentence about what it does
- Slide 2: context — the real problem this project solves (from README/CLAUDE.md)
- Middle: evidence in narrative order (see domain arc below)
- Second-to-last: takeaways — 3-5 specific things learned, grounded in actual work
- Last: next_steps — concrete next actions visible from the current state

═══════════════════════════════
THE SLOGAN TECHNIQUE — MANDATORY
═══════════════════════════════
Every slide heading MUST be a complete conclusion or finding — NOT a label or topic.

WRONG: "Results"  →  RIGHT: "The Model Reached 94.3% Accuracy, Beating Baseline by 12 Points"
WRONG: "Architecture"  →  RIGHT: "Three Microservices Replace the Monolith, Cutting Deploy Time 60%"
WRONG: "Data Overview"  →  RIGHT: "Churn Spikes on Day 7 — Users Who Skip Onboarding Leave 3× Faster"

If you cannot state a finding for a slide, that content does not deserve its own slide.

════════════════════════════════
CONTENT-TO-LAYOUT SIGNAL TABLE
════════════════════════════════
Match content to slide type using these signals:

Content signal                      → Required type
Single number / % result            → metric_callout
Image or chart file present         → image / chart  (NEVER bullets for visual content)
Two contrasting states / before+after → comparison
3–6 discrete items / features       → feature_grid
Sequential stages / steps / process → timeline
CSV rows / tabular data             → table
Flowing argument, ≤3 key points     → context
Summary of learned lessons          → takeaways
Forward-looking actions             → next_steps

NEVER use "context" (bullets) when another type fits the content.
MAXIMUM 3 bullet points per context/takeaways/next_steps slide.
EVERY non-title slide must have ONE dominant visual: a large number, chart, image, or grid.

═══════════════
SLIDE TYPES
═══════════════
metric_callout   → ONE large number from the files. Heading = what it means.
chart/image      → Heading = conclusion from the visual (not "Chart of X").
code             → MAX 2 per deck. 5-8 most important lines only. Never a whole file.
comparison       → Before vs. after — only if both states appear in the files.
table            → CSV data, max 8 rows, real column names and values.
feature_grid     → 3-6 items as grid cards. Each bullet becomes one card (format: "Title: description").
timeline         → Sequential steps/stages. Each bullet = one step.
takeaways        → MAX 3 bullets. Each is a complete sentence with a specific detail.
context/next_steps → MAX 3 bullets. Default for flowing narrative content.
section_divider  → Visual break between narrative sections. Heading = section title (e.g. "Architecture").
                   Use once per major narrative section, not for every slide.
statement        → One powerful single-sentence claim. No bullets. Used for "so what" moments.

══════════════════════════════
SLIDE VARIETY RULES — MANDATORY
══════════════════════════════
1. You MUST use at least 5 different slide types across the deck.
2. If ANY image or chart file in artifacts → MUST include image/chart slide.
3. If ANY CSV file → MUST include metric_callout or table slide.
4. If 3+ discrete features/components → MUST include feature_grid slide.
5. A deck where every slide is "context" bullets is a complete failure.

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
First line of your output must be: Visual strategy: [one sentence describing the dominant \
visual element and why it communicates the slide's message]. Then the HTML.

STRICT RULES:
1. data-auto-animate on every <section>.
2. class="fragment" on every <li>.
3. USE THE EXACT HEADING from SlideSpec — never replace with a generic label like "Results".
4. ALL TEXT IS LEFT-ALIGNED. Add style="text-align:left" to every <ul>, <ol>, and <p> block.
   Only .hero-metric and title slides may use text-align:center.
5. CODE slides: MAXIMUM 6 LINES. Cut mercilessly. One subtitle sentence explaining why.
6. Never invent facts. Use only content from SlideSpec and Artifacts.
7. No <style> tags. CSS vars: --accent, --fg, --fg2, --dim, --surface, --border
   CSS classes: r-fit-text, r-stretch, hero-metric, metric-label, metric-desc,
                subtitle, slide-split, slide-grid, grid-card, timeline-row, t-step, t-num

TEMPLATES:

code:
<section data-auto-animate>
  <h2>{EXACT HEADING}</h2>
  <pre><code class="language-python" data-trim data-line-numbers>
{MAX 6 LINES — the most important only}
  </code></pre>
  <p class="subtitle" style="text-align:left">{why this design decision matters}</p>
  <aside class="notes">{2-3 specific sentences referencing file/function names}</aside>
</section>

comparison:
<section data-auto-animate>
  <h2>{EXACT HEADING}</h2>
  <div class="slide-split">
    <div>
      <p style="color:var(--dim);font-size:.65em;text-transform:uppercase;margin-bottom:.4em">Before</p>
      <p class="fragment" style="text-align:left">{specific before state}</p>
    </div>
    <div>
      <p style="color:var(--accent);font-size:.65em;text-transform:uppercase;margin-bottom:.4em">After</p>
      <p class="fragment" style="text-align:left">{specific after state — the improvement}</p>
    </div>
  </div>
  <aside class="notes">{why this change, measured impact}</aside>
</section>

table:
<section data-auto-animate>
  <h2>{EXACT HEADING}</h2>
  <table style="width:100%;border-collapse:collapse;font-size:.78em;text-align:left">
    <thead><tr style="border-bottom:2px solid var(--accent)">
      <th style="padding:.4em .8em">{col}</th><th style="padding:.4em .8em">{col}</th>
    </tr></thead>
    <tbody>
      <tr class="fragment"><td style="padding:.35em .8em">{val}</td><td style="padding:.35em .8em">{val}</td></tr>
    </tbody>
  </table>
  <p class="subtitle" style="text-align:left">{key pattern from this data}</p>
  <aside class="notes">{what action this data suggests}</aside>
</section>

general content (bullets only — max 3 items):
<section data-auto-animate>
  <h2>{EXACT HEADING}</h2>
  <ul style="text-align:left">
    <li class="fragment">{use bullet_points from spec verbatim}</li>
    <li class="fragment">{second point}</li>
    <li class="fragment">{third point — no more than 3}</li>
  </ul>
  <aside class="notes">{2-3 specific sentences}</aside>
</section>

EXAMPLE (metric_callout — for reference):
<section data-auto-animate>
  <p class="metric-label">KEY RESULT</p>
  <h2 class="r-fit-text hero-metric">94.3%</h2>
  <p class="metric-desc">Validation accuracy after 28 epochs — 12 points above the baseline</p>
  <aside class="notes">Loss plateaued at epoch 28 per training_log.txt. The jump from 82% came after adding dropout layers in commit a3f2c1.</aside>
</section>

section_divider:
<section data-auto-animate>
  <div class="section-divider">
    <span class="sec-num">{slide id zero-padded}</span>
    <p class="sec-label">Section {N}</p>
    <h2 class="sec-title">{EXACT HEADING}</h2>
    <p class="subtitle">{one sentence from insight}</p>
  </div>
  <aside class="notes">{what this section covers}</aside>
</section>

statement:
<section data-auto-animate>
  <div class="statement-slide">
    <p class="stmt">{EXACT HEADING — the big claim}</p>
    <p class="subtitle">{one supporting sentence from insight}</p>
  </div>
  <aside class="notes">{evidence and context for this claim}</aside>
</section>

EXAMPLE (split layout — code + explanation):
<section data-auto-animate>
  <h2>Two-Pass Pipeline Eliminates Context Overflow</h2>
  <div class="slide-split">
    <div>
      <p style="text-align:left;font-size:.82em">The Planner generates a JSON outline in Pass 1. The Coder renders each slide independently in Pass 2 — no slide ever sees the full context.</p>
      <p class="fragment" style="text-align:left;font-size:.82em">Result: consistent quality regardless of project size.</p>
    </div>
    <div>
      <pre><code class="language-python" data-trim>
outline = planner(files)
for slide in outline:
    html = coder(slide)
      </code></pre>
    </div>
  </div>
  <aside class="notes">Commit 2baf786 introduced this split. Before: the model would lose early slide context by slide 8. After: every slide is rendered fresh.</aside>
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

# Comprehensive font URL — covers all themes
_ALL_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=JetBrains+Mono:wght@400;500;700;800"
    "&family=DM+Serif+Display:ital@0;1"
    "&family=IBM+Plex+Sans:wght@300;400;500;700"
    "&family=IBM+Plex+Sans+Condensed:wght@400;600;700"
    "&family=Instrument+Serif:ital@0;1"
    "&family=Space+Grotesk:wght@300;400;500;600;700"
    "&family=Barlow+Condensed:wght@300;500;700;900"
    "&family=IBM+Plex+Mono:wght@300;400;500;600"
    "&family=Archivo+Black"
    "&family=Space+Mono:wght@400;700"
    "&display=swap"
)

# Shared utility classes appended to every theme
_SHARED_CLASSES = """
    .reveal pre, .reveal code {{ font-family: 'JetBrains Mono', monospace; }}
    .reveal .r-fit-text {{ line-height: 1; }}
    .slide-split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2.5rem; align-items: start; margin-top: 1rem; }}
    .slide-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: .9rem; flex: 1; margin-top: .6rem; }}
    .timeline-row {{ display: flex; gap: 0; margin-top: 1rem; flex: 1; }}
    .t-step {{ flex: 1; padding: 1rem; border-top: 3px solid var(--border); }}
    .t-step.fragment.visible {{ border-top-color: var(--accent); }}
    .t-step p {{ font-size: .76rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
"""

# Theme skeletons — {accent}, {font_heading}, {font_body} filled by Designer Agent
_THEME_SKELETONS: dict[str, str] = {

    # ── 1. EDITORIAL PRESS ────────────────────────────────────────────────────
    # Cream stock, DM Serif Display, scarlet accent, masthead chrome, magazine spreads
    "editorial-press": """
        :root {{
            --accent: {accent};
            --fg: #1a1614; --fg2: #4b3e35; --bg: #f4ede2;
            --surface: #ede5d5; --border: #1a1614; --dim: #6b5e57;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'IBM Plex Sans', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 4.5rem 4.5rem 3.5rem;
            display: flex; flex-direction: column; justify-content: flex-start;
            border-top: 1px solid var(--border);
        }}
        .reveal h1 {{
            font-family: 'DM Serif Display', serif; font-weight: 400;
            font-size: clamp(3rem,9vw,6.5rem); line-height: .88;
            letter-spacing: -.04em; color: var(--fg); margin: 0 0 .35em;
        }}
        .reveal h1 em {{ color: {accent}; font-style: italic; }}
        .reveal h2 {{
            font-family: 'DM Serif Display', serif; font-weight: 400;
            font-size: clamp(1.4rem,3.5vw,2.2rem); line-height: 1.1;
            letter-spacing: -.02em; color: var(--fg); margin: 0 0 .9em;
            padding-bottom: .3em; border-bottom: 1px solid var(--border);
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%;
            display: grid; grid-template-columns: 1fr 1fr; gap: 1.4rem 2.5rem; align-content: start;
            counter-reset: li; }}
        .reveal li {{
            display: grid; grid-template-columns: 3.2rem 1fr; gap: .8rem;
            padding-top: .9rem; border-top: 1px solid var(--border); align-items: start;
            counter-increment: li;
        }}
        .reveal li::before {{
            font-family: 'DM Serif Display', serif; font-size: 2.6rem; line-height: .85;
            color: {accent}; content: counter(li, decimal-leading-zero); flex-shrink: 0;
        }}
        .reveal li .li-num {{ display: none; }}
        .reveal li .li-body, .reveal li > span:not(.li-num) {{ font-size: .82em; line-height: 1.5; }}
        .reveal li b {{ font-weight: 600; }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 1px solid var(--border); border-radius: 0; }}
        .reveal pre code {{ font-size: .7em; background: var(--surface); padding: 1em; line-height: 1.6; }}
        .reveal .progress {{ background: {accent}; height: 2px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; }}
        .subtitle {{ font-family: 'DM Serif Display', serif; font-style: italic; color: var(--fg2); font-size: .85em; margin-top: .4em; line-height: 1.35; }}
        .hero-metric {{
            font-family: 'DM Serif Display', serif; font-weight: 400;
            font-size: clamp(5rem,18vw,10rem); line-height: .82; color: var(--fg);
            letter-spacing: -.05em; display: block;
        }}
        .hero-metric .u {{ color: {accent}; font-style: italic; font-size: .55em; }}
        .metric-label {{
            font-family: 'IBM Plex Sans Condensed', sans-serif; font-weight: 600;
            font-size: .62em; letter-spacing: .22em; text-transform: uppercase;
            color: {accent}; margin-bottom: .4em;
        }}
        .metric-desc {{
            font-family: 'DM Serif Display', serif; font-style: italic;
            font-size: .85em; color: var(--fg2); margin-top: .5em; line-height: 1.4;
            border-left: 1px solid var(--border); padding-left: 1rem;
        }}
        .grid-card {{
            background: var(--surface); border: 1px solid var(--border); padding: 1rem;
            display: grid; grid-template-rows: auto 1fr;
        }}
        .grid-card h4 {{
            font-family: 'IBM Plex Sans', sans-serif; font-size: .78rem; font-weight: 600;
            color: var(--fg); margin: 0 0 .3em;
        }}
        .grid-card p {{ font-family: 'DM Serif Display', serif; font-style: italic; font-size: .76rem; color: var(--fg2); margin: 0; line-height: 1.45; }}
        .t-num {{ font-family: 'DM Serif Display', serif; font-size: 2.2rem; color: {accent}; font-weight: 400; display: block; margin-bottom: .25em; }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; position: relative; overflow: hidden; }}
        .section-divider .sec-num {{
            position: absolute; right: -2rem; top: 50%; transform: translateY(-50%);
            font-family: 'DM Serif Display', serif; font-style: italic;
            font-size: clamp(8rem,28vw,18rem); line-height: .8; color: {accent};
            opacity: 0.18; letter-spacing: -.05em; pointer-events: none;
        }}
        .section-divider .sec-label {{
            font-family: 'IBM Plex Sans Condensed', sans-serif; font-weight: 600;
            font-size: .62em; letter-spacing: .24em; text-transform: uppercase; color: {accent}; margin-bottom: .5rem;
        }}
        .section-divider .sec-title {{
            font-family: 'DM Serif Display', serif; font-weight: 400;
            font-size: clamp(2.5rem,8vw,5.5rem); line-height: .9; margin: 0; letter-spacing: -.03em; color: var(--fg);
        }}
        .section-divider .sec-title em {{ font-style: italic; color: {accent}; }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{
            font-family: 'DM Serif Display', serif; font-size: clamp(2.2rem,6vw,4.2rem);
            font-weight: 400; line-height: 1.05; letter-spacing: -.025em; color: var(--fg);
        }}
        .statement-slide .stmt em {{ color: {accent}; font-style: italic; }}
    """,

    # ── 3. GRADIENT DREAMSCAPE ────────────────────────────────────────────────
    # Deep purple mesh, Instrument Serif italic, glass cards, gradient text fills
    "gradient-dreamscape": """
        :root {{
            --accent: {accent};
            --fg: #f4ecff; --fg2: rgba(244,236,255,.68); --bg: #110a26;
            --surface: rgba(255,255,255,0.06); --border: rgba(255,255,255,0.12); --dim: rgba(244,236,255,.4);
        }}
        .reveal-viewport {{
            background:
                radial-gradient(circle at 22% 28%, rgba(217,70,239,0.55) 0%, transparent 38%),
                radial-gradient(circle at 80% 15%, rgba(245,158,11,0.35) 0%, transparent 26%),
                radial-gradient(circle at 90% 80%, rgba(6,182,212,0.45) 0%, transparent 38%),
                radial-gradient(circle at 8% 88%, rgba(99,102,241,0.5) 0%, transparent 42%),
                #110a26;
        }}
        .reveal {{ font-family: 'Space Grotesk', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 3.5rem 4.5rem;
            display: flex; flex-direction: column; justify-content: flex-start;
            background-image: repeating-linear-gradient(
                0deg, rgba(255,255,255,0.022) 0, rgba(255,255,255,0.022) 1px,
                transparent 1px, transparent 3px),
                radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.4) 100%);
        }}
        .reveal h1 {{
            font-family: 'Instrument Serif', serif; font-style: italic; font-weight: 400;
            font-size: clamp(3rem,9vw,6rem); line-height: .88; margin: 0 0 .4em;
            letter-spacing: -.03em;
            background: linear-gradient(135deg, #fef3c7 0%, #fbcfe8 35%, #c4b5fd 70%, #7dd3fc 100%);
            -webkit-background-clip: text; background-clip: text; color: transparent;
        }}
        .reveal h2 {{
            font-family: 'Instrument Serif', serif; font-style: italic; font-weight: 400;
            font-size: clamp(1.4rem,3.5vw,2.2rem); line-height: 1.05; margin: 0 0 .8em;
            background: linear-gradient(120deg, #fef3c7, #fbcfe8 50%, #c4b5fd);
            -webkit-background-clip: text; background-clip: text; color: transparent;
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%;
            display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; align-content: start; }}
        .reveal li {{
            background: var(--surface); backdrop-filter: blur(24px);
            border: 1px solid var(--border); border-radius: 1.2rem;
            padding: 1.1rem 1.3rem; font-size: .84em; line-height: 1.5; color: var(--fg);
        }}
        .reveal li::before {{ display: none; }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 1px solid var(--border); border-radius: .5rem; }}
        .reveal pre code {{ font-size: .7em; background: rgba(0,0,0,0.4); padding: 1em; line-height: 1.6; }}
        .reveal .progress {{ background: {accent}; height: 3px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; }}
        .subtitle {{
            font-family: 'Instrument Serif', serif; font-style: italic;
            color: var(--fg2); font-size: .82em; margin-top: .4em; line-height: 1.35; max-width: 30ch;
        }}
        .hero-metric {{
            font-family: 'Instrument Serif', serif; font-style: italic; font-weight: 400;
            font-size: clamp(5rem,18vw,10rem); line-height: .8; letter-spacing: -.05em; display: block;
            background: linear-gradient(135deg, #fef3c7 0%, #fbcfe8 30%, #c4b5fd 60%, #7dd3fc 100%);
            -webkit-background-clip: text; background-clip: text; color: transparent;
        }}
        .metric-label {{ font-family: 'Space Grotesk', sans-serif; font-weight: 500; font-size: .62em; letter-spacing: .32em; text-transform: uppercase; color: #fbcfe8; margin-bottom: .4em; }}
        .metric-desc {{
            background: var(--surface); backdrop-filter: blur(24px);
            border: 1px solid var(--border); border-radius: 1.2rem;
            padding: .9rem 1.2rem; font-size: .78em; color: var(--fg2); margin-top: .6em; line-height: 1.55;
        }}
        .grid-card {{
            background: var(--surface); backdrop-filter: blur(24px);
            border: 1px solid var(--border); border-radius: 1.4rem; padding: 1.1rem 1.3rem;
        }}
        .grid-card h4 {{ font-family: 'Instrument Serif', serif; font-style: italic; font-size: .84rem; font-weight: 400; color: #fff; margin: 0 0 .3em; }}
        .grid-card p {{ font-size: .73rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-step {{ background: var(--surface); backdrop-filter: blur(20px); border: 1px solid var(--border); border-radius: .8rem; padding: 1rem; border-top: 1px solid var(--border); }}
        .t-step.fragment.visible {{ border-color: {accent}; }}
        .t-num {{ font-family: 'Instrument Serif', serif; font-style: italic; font-size: 2.2rem; color: {accent}; font-weight: 400; display: block; margin-bottom: .3em; }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .section-divider .sec-num {{
            font-family: 'Instrument Serif', serif; font-style: italic;
            font-size: clamp(6rem,22vw,14rem); font-weight: 400; line-height: .85; letter-spacing: -.04em;
            background: linear-gradient(120deg, #fef3c7, #fbcfe8 40%, #c4b5fd);
            -webkit-background-clip: text; background-clip: text; color: transparent;
            opacity: 0.55;
        }}
        .section-divider .sec-label {{ color: #fbcfe8; font-size: .6em; letter-spacing: .35em; text-transform: uppercase; margin: .3rem 0; }}
        .section-divider .sec-title {{
            font-family: 'Instrument Serif', serif; font-style: italic; font-weight: 400;
            font-size: clamp(2rem,6vw,4.5rem); line-height: .9; margin: 0; letter-spacing: -.025em;
            background: linear-gradient(120deg, #fef3c7, #fbcfe8 50%, #c4b5fd);
            -webkit-background-clip: text; background-clip: text; color: transparent;
        }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{
            font-family: 'Instrument Serif', serif; font-style: italic; font-weight: 400;
            font-size: clamp(2.2rem,6vw,4.5rem); line-height: 1.08; letter-spacing: -.02em;
            background: linear-gradient(135deg, #fef3c7 0%, #fbcfe8 35%, #c4b5fd 70%, #7dd3fc 100%);
            -webkit-background-clip: text; background-clip: text; color: transparent;
        }}
        .statement-slide .stmt em {{ font-style: normal; }}
    """,

    # ── 4. BLUEPRINT ──────────────────────────────────────────────────────────
    # Navy + cyan engineering grid, Barlow Condensed 900, amber dimension lines
    "blueprint": """
        :root {{
            --accent: {accent};
            --fg: #e8f1fa; --fg2: #b9d2e3; --bg: #0c1e2f;
            --surface: rgba(80,156,207,0.06); --border: rgba(110,168,201,0.4); --dim: #6ea8c9;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'IBM Plex Mono', monospace; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 3.5rem 4.5rem 4rem;
            display: flex; flex-direction: column; justify-content: flex-start;
            background-image:
                linear-gradient(rgba(80,156,207,0.07) 1px, transparent 1px),
                linear-gradient(90deg, rgba(80,156,207,0.07) 1px, transparent 1px),
                linear-gradient(rgba(80,156,207,0.16) 1px, transparent 1px),
                linear-gradient(90deg, rgba(80,156,207,0.16) 1px, transparent 1px);
            background-size: 2.5rem 2.5rem, 2.5rem 2.5rem, 12.5rem 12.5rem, 12.5rem 12.5rem;
        }}
        /* Corner registration marks */
        .reveal .slides section::before,
        .reveal .slides section::after {{
            content: ""; position: absolute; width: 2.5rem; height: 2.5rem;
            border: 2px solid {accent}; pointer-events: none;
        }}
        .reveal .slides section::before {{ top: 1.2rem; left: 1.2rem; border-right: none; border-bottom: none; }}
        .reveal .slides section::after  {{ bottom: 1.2rem; right: 1.2rem; border-left: none; border-top: none; }}
        .reveal h1 {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(3rem,9vw,6rem); line-height: .88; text-transform: uppercase;
            letter-spacing: .01em; color: #fcfeff; margin: 0 0 .4em;
        }}
        .reveal h1::before {{
            content: "FILE — "; color: {accent};
            font-size: .4em; letter-spacing: .22em; display: block; margin-bottom: .5rem;
        }}
        .reveal h2 {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(1.5rem,3.5vw,2.2rem); line-height: 1.0; text-transform: uppercase;
            letter-spacing: .008em; color: #fcfeff; margin: 0 0 .8em;
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%; display: flex; flex-direction: column; gap: .55rem; }}
        .reveal li {{
            display: grid; grid-template-columns: 5rem 1fr auto; gap: 1.2rem;
            border: 1px solid var(--border); padding: .7rem .9rem;
            background: var(--surface); align-items: center;
            font-size: .82em; line-height: 1.4; color: var(--fg);
            counter-increment: li;
        }}
        .reveal li::before {{
            content: "DEL-" counter(li, decimal-leading-zero);
            color: {accent}; font-size: .75em; letter-spacing: .04em;
            border-right: 1px solid rgba(255,184,77,0.4); padding-right: .8rem;
        }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 1px solid var(--border); border-radius: 0; }}
        .reveal pre code {{ font-size: .7em; background: rgba(0,0,0,0.35); padding: 1em; line-height: 1.6; }}
        .reveal .progress {{ background: {accent}; height: 2px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; letter-spacing: .12em; }}
        .subtitle {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 500;
            font-size: .82em; color: var(--fg2); text-transform: uppercase;
            letter-spacing: .02em; line-height: 1.25; margin-top: .4em;
        }}
        .hero-metric {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(5rem,18vw,11rem); line-height: .86; color: #fcfeff;
            letter-spacing: -.01em; display: block; text-transform: uppercase;
        }}
        .hero-metric .u {{ color: {accent}; font-size: .55em; }}
        .metric-label {{
            color: {accent}; font-size: .6em; letter-spacing: .32em; text-transform: uppercase;
            display: flex; align-items: center; gap: .8rem; margin-bottom: .4em;
        }}
        .metric-label::before {{ content: ""; display: inline-block; width: 2rem; height: 1px; background: {accent}; }}
        .metric-desc {{
            border: 1px solid var(--border); padding: .75rem 1rem;
            font-size: .74em; color: var(--fg2); margin-top: .5em; line-height: 1.7;
            letter-spacing: .04em;
        }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); padding: .9rem; }}
        .grid-card h4 {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 700;
            font-size: .78rem; text-transform: uppercase; letter-spacing: .04em;
            color: {accent}; margin: 0 0 .3em;
        }}
        .grid-card p {{ font-size: .72rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-num {{
            font-family: 'Barlow Condensed', sans-serif; font-size: 2rem;
            color: {accent}; font-weight: 900; display: block; margin-bottom: .3em; text-transform: uppercase;
        }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .section-divider .sec-num {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(7rem,24vw,16rem); line-height: .82; color: #fcfeff;
            letter-spacing: -.02em; text-transform: uppercase;
        }}
        .section-divider .sec-label {{
            color: {accent}; font-size: .6em; letter-spacing: .4em; text-transform: uppercase;
            display: flex; align-items: center; gap: 1rem; margin-bottom: .5rem;
        }}
        .section-divider .sec-label::before, .section-divider .sec-label::after {{
            content: ""; height: 1px; background: {accent};
        }}
        .section-divider .sec-label::before {{ width: 3rem; }}
        .section-divider .sec-label::after {{ flex: 1; max-width: 8rem; }}
        .section-divider .sec-title {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(2rem,6vw,4rem); line-height: .9; text-transform: uppercase; letter-spacing: .01em; color: #fcfeff; margin: 0;
        }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(2.2rem,6.5vw,5rem); line-height: .9; text-transform: uppercase;
            letter-spacing: .01em; color: #fcfeff;
        }}
        .statement-slide .stmt em {{ color: {accent}; font-style: normal; }}
    """,

    # ── 5. SWISS BRUTALISM ────────────────────────────────────────────────────
    # Warm white, Archivo Black, single electric accent circle, hard rules
    "swiss-brutalism": """
        :root {{
            --accent: {accent};
            --fg: #0a0a0a; --fg2: #44423e; --bg: #f5f4ef;
            --surface: #ebebе5; --border: #0a0a0a; --dim: #767470;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'Space Grotesk', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 4rem 5rem 3.5rem;
            display: flex; flex-direction: column; justify-content: flex-start;
            border-top: 3px solid var(--fg);
        }}
        .reveal h1 {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(3rem,9vw,6.5rem); line-height: .84;
            letter-spacing: -.045em; text-transform: uppercase; color: var(--fg); margin: 0 0 .4em;
        }}
        .reveal h2 {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(1.5rem,3.5vw,2.3rem); line-height: .92;
            letter-spacing: -.035em; text-transform: uppercase; color: var(--fg); margin: 0 0 .8em;
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%;
            display: grid; grid-template-columns: 1fr 1fr; gap: 1.4rem 2.5rem; align-content: start;
            counter-reset: li; }}
        .reveal li {{
            display: grid; grid-template-columns: 4rem 1fr; gap: 1rem;
            border-top: 3px solid var(--fg); padding-top: .9rem; align-items: start;
            counter-increment: li;
        }}
        .reveal li::before {{
            font-family: 'Archivo Black', sans-serif; font-size: 2.4rem;
            line-height: .88; letter-spacing: -.03em;
            content: counter(li, decimal-leading-zero);
            color: {accent};
        }}
        .reveal li:nth-child(even)::before {{ color: var(--fg); }}
        .reveal li > *:not(::before) {{ font-size: .82em; line-height: 1.45; }}
        .reveal li b {{ font-weight: 700; }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 3px solid var(--fg); border-radius: 0; }}
        .reveal pre code {{ font-size: .7em; background: #ebebе5; padding: 1em; line-height: 1.6; color: var(--fg); }}
        .reveal .progress {{ background: {accent}; height: 3px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; font-family: 'Space Mono', monospace; letter-spacing: .06em; }}
        .subtitle {{ font-family: 'Space Grotesk', sans-serif; font-weight: 500; color: var(--fg2); font-size: .8em; margin-top: .4em; line-height: 1.3; max-width: 32ch; }}
        .hero-metric {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(5rem,18vw,11rem); line-height: .82; letter-spacing: -.055em;
            display: block; text-transform: uppercase; position: relative;
        }}
        /* Accent circle behind metric number — CSS-only dot trick */
        .hero-metric::before {{
            content: ""; position: absolute;
            width: clamp(5rem,16vw,9rem); height: clamp(5rem,16vw,9rem);
            background: {accent}; border-radius: 50%;
            left: .3em; top: .1em; z-index: -1;
        }}
        .metric-label {{ font-family: 'Space Mono', monospace; font-size: .6em; letter-spacing: .18em; text-transform: uppercase; color: var(--dim); margin-bottom: .4em; }}
        .metric-desc {{ border-left: 3px solid var(--fg); padding-left: .9rem; font-size: .78em; color: var(--fg2); margin-top: .5em; line-height: 1.45; }}
        .grid-card {{ border-top: 3px solid var(--fg); padding-top: .9rem; }}
        .grid-card h4 {{ font-family: 'Archivo Black', sans-serif; font-size: .78rem; font-weight: 900; text-transform: uppercase; letter-spacing: -.01em; color: {accent}; margin: 0 0 .3em; }}
        .grid-card p {{ font-family: 'Space Mono', monospace; font-size: .7rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-step {{ border-top: 3px solid var(--fg); padding-top: .9rem; }}
        .t-step.fragment.visible {{ border-top-color: {accent}; }}
        .t-num {{ font-family: 'Archivo Black', sans-serif; font-size: 2.2rem; color: {accent}; font-weight: 900; display: block; margin-bottom: .3em; letter-spacing: -.03em; }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; border-top: 3px solid var(--fg); padding-top: 1.5rem; }}
        .section-divider .sec-num {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(7rem,22vw,14rem); line-height: .8; color: {accent};
            letter-spacing: -.05em; text-transform: uppercase; align-self: flex-end;
        }}
        .section-divider .sec-label {{
            font-family: 'Space Mono', monospace; font-size: .6em; letter-spacing: .2em;
            text-transform: uppercase; color: var(--dim); margin-bottom: .4rem;
            display: flex; align-items: center; gap: 1rem;
        }}
        .section-divider .sec-label::before {{ content: ""; width: 1.2rem; height: 1.2rem; background: {accent}; border-radius: 50%; flex-shrink: 0; }}
        .section-divider .sec-title {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(2.2rem,6vw,5rem); line-height: .88; text-transform: uppercase;
            letter-spacing: -.04em; color: var(--fg); margin: 0;
        }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(2.5rem,7vw,5.5rem); line-height: .88;
            letter-spacing: -.04em; text-transform: uppercase; color: var(--fg);
        }}
        .statement-slide .stmt em {{ color: {accent}; font-style: normal; }}
    """,

    # ── 6. HARVEST ────────────────────────────────────────────────────────────
    # Screenshots: dark-green creative agency + harvest agriculture bold orange
    # Deep forest green bg, warm orange accent, photography-card grid, bold Barlow
    "harvest": """
        :root {{
            --accent: {accent};
            --fg: #f5f0e8; --fg2: #a8c4a0; --bg: #0d2116;
            --surface: rgba(255,255,255,0.06); --border: rgba(255,255,255,0.12); --dim: #4a7a58;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'Barlow Condensed', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 3.5rem 4.5rem;
            display: flex; flex-direction: column; justify-content: flex-start;
        }}
        .reveal h1 {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(3rem,9vw,6.5rem); line-height: .86;
            letter-spacing: -.01em; text-transform: uppercase; color: var(--fg); margin: 0 0 .4em;
        }}
        .reveal h2 {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 700;
            font-size: clamp(1.5rem,3.5vw,2.4rem); line-height: 1.0;
            letter-spacing: .01em; text-transform: uppercase; color: var(--fg); margin: 0 0 .8em;
            padding-left: 1rem; border-left: 5px solid {accent};
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%; counter-reset: li; }}
        .reveal li {{
            counter-increment: li; padding: .65em 0;
            border-bottom: 1px solid var(--border); font-size: .86em; line-height: 1.5; color: var(--fg);
            display: grid; grid-template-columns: 2.8rem 1fr; gap: 1rem; align-items: baseline;
        }}
        .reveal li::before {{ content: counter(li, decimal-leading-zero); color: {accent}; font-weight: 700; font-size: .9em; }}
        .reveal pre {{ width: 100%; margin: .5em 0; border-radius: 4px; border: 1px solid var(--border); }}
        .reveal pre code {{ font-size: .7em; background: rgba(0,0,0,0.4); padding: 1em; line-height: 1.6; }}
        .reveal .progress {{ background: {accent}; height: 3px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; }}
        .subtitle {{ color: var(--fg2); font-size: .8em; margin-top: .4em; line-height: 1.4; }}
        .hero-metric {{
            font-family: 'Barlow Condensed', sans-serif; font-weight: 900;
            font-size: clamp(5rem,20vw,12rem); line-height: .82; color: {accent};
            letter-spacing: -.02em; display: block; text-transform: uppercase;
        }}
        .metric-label {{ font-size: .6em; letter-spacing: .2em; text-transform: uppercase; color: var(--fg2); margin-bottom: .3em; }}
        .metric-desc {{ font-size: .76em; color: var(--fg2); margin-top: .4em; line-height: 1.45; }}
        .grid-card {{
            background: var(--surface); border: 1px solid var(--border);
            border-top: 3px solid {accent}; padding: 1rem; border-radius: 2px;
        }}
        .grid-card h4 {{ font-family: 'Barlow Condensed', sans-serif; font-size: .82rem; font-weight: 700; text-transform: uppercase; color: {accent}; margin: 0 0 .3em; letter-spacing: .04em; }}
        .grid-card p {{ font-size: .74rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-num {{ font-family: 'Barlow Condensed', sans-serif; font-size: 2rem; color: {accent}; font-weight: 900; display: block; margin-bottom: .3em; }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .section-divider .sec-num {{ font-family: 'Barlow Condensed', sans-serif; font-weight: 900; font-size: clamp(7rem,24vw,16rem); line-height: .82; color: {accent}; letter-spacing: -.03em; text-transform: uppercase; }}
        .section-divider .sec-label {{ color: var(--dim); font-size: .6em; letter-spacing: .22em; text-transform: uppercase; margin: .4rem 0 .2rem; }}
        .section-divider .sec-title {{ font-family: 'Barlow Condensed', sans-serif; font-weight: 900; font-size: clamp(2rem,6vw,4.5rem); line-height: .9; text-transform: uppercase; color: var(--fg); margin: 0; padding-left: 1rem; border-left: 5px solid {accent}; }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{ font-family: 'Barlow Condensed', sans-serif; font-weight: 900; font-size: clamp(2.5rem,7vw,5.5rem); line-height: .88; text-transform: uppercase; color: var(--fg); }}
        .statement-slide .stmt em {{ color: {accent}; font-style: normal; }}
    """,

    # ── 7. NEON NOIR ──────────────────────────────────────────────────────────
    # Screenshots: blue glowing project-proposal + dark teal town-hall
    # Near-black, electric blue + cyan dual glow, glowing borders, 2025 SaaS energy
    "neon-noir": """
        :root {{
            --accent: {accent};
            --fg: #e8f4ff; --fg2: rgba(232,244,255,.6); --bg: #050810;
            --surface: rgba(29,78,216,0.08); --border: rgba(29,78,216,0.35); --dim: rgba(232,244,255,.35);
            --glow: {accent}55;
        }}
        .reveal-viewport {{
            background: radial-gradient(ellipse at 30% 20%, rgba(29,78,216,0.25) 0%, transparent 55%),
                         radial-gradient(ellipse at 80% 80%, rgba(6,182,212,0.18) 0%, transparent 50%),
                         #050810;
        }}
        .reveal {{ font-family: 'Space Grotesk', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 3.5rem 4.5rem;
            display: flex; flex-direction: column; justify-content: flex-start;
            border: 1px solid var(--border);
            box-shadow: inset 0 0 60px rgba(29,78,216,0.05), 0 0 0 1px var(--glow);
        }}
        .reveal h1 {{
            font-family: 'Space Grotesk', sans-serif; font-weight: 700;
            font-size: clamp(2.8rem,8vw,5.5rem); line-height: .9;
            letter-spacing: -.04em; color: var(--fg); margin: 0 0 .4em;
            text-shadow: 0 0 40px {accent}88;
        }}
        .reveal h2 {{
            font-family: 'Space Grotesk', sans-serif; font-weight: 600;
            font-size: clamp(1.3rem,3vw,2rem); line-height: 1.1;
            letter-spacing: -.02em; color: var(--fg); margin: 0 0 .85em;
            border-bottom: 1px solid var(--border); padding-bottom: .4em;
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%; counter-reset: li; }}
        .reveal li {{
            counter-increment: li; padding: .6em 1rem;
            margin-bottom: .5rem;
            background: var(--surface); border: 1px solid var(--border);
            font-size: .86em; line-height: 1.55; color: var(--fg);
            display: grid; grid-template-columns: 2.4rem 1fr; gap: .8rem; align-items: baseline;
        }}
        .reveal li::before {{ content: counter(li, decimal-leading-zero); color: {accent}; font-size: .8em; font-weight: 600; }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 1px solid var(--border); border-radius: 4px; }}
        .reveal pre code {{ font-size: .7em; background: rgba(0,0,0,0.5); padding: 1em; line-height: 1.6; }}
        .reveal .progress {{ background: {accent}; height: 2px; box-shadow: 0 0 8px {accent}; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; }}
        .subtitle {{ color: var(--fg2); font-size: .78em; margin-top: .35em; line-height: 1.4; }}
        .hero-metric {{
            font-family: 'Space Grotesk', sans-serif; font-weight: 700;
            font-size: clamp(5rem,18vw,10rem); line-height: .86; color: {accent};
            letter-spacing: -.05em; display: block;
            text-shadow: 0 0 60px {accent}88, 0 0 120px {accent}44;
        }}
        .metric-label {{ font-size: .6em; letter-spacing: .22em; text-transform: uppercase; color: var(--dim); margin-bottom: .35em; }}
        .metric-desc {{ background: var(--surface); border: 1px solid var(--border); padding: .75rem 1rem; font-size: .76em; color: var(--fg2); margin-top: .5em; line-height: 1.5; border-radius: 4px; }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 1rem; }}
        .grid-card h4 {{ font-size: .78rem; font-weight: 600; color: {accent}; margin: 0 0 .3em; text-shadow: 0 0 12px {accent}66; }}
        .grid-card p {{ font-size: .72rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-num {{ font-size: 2rem; font-weight: 700; color: {accent}; display: block; margin-bottom: .3em; text-shadow: 0 0 20px {accent}66; }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .section-divider .sec-num {{ font-weight: 700; font-size: clamp(6rem,22vw,13rem); line-height: .85; color: {accent}; letter-spacing: -.05em; text-shadow: 0 0 80px {accent}66; opacity: .7; }}
        .section-divider .sec-label {{ color: var(--dim); font-size: .6em; letter-spacing: .22em; text-transform: uppercase; margin: .3rem 0; }}
        .section-divider .sec-title {{ font-weight: 600; font-size: clamp(1.8rem,5vw,3.5rem); line-height: .95; color: var(--fg); margin: 0; text-shadow: 0 0 30px {accent}44; }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{ font-weight: 700; font-size: clamp(2rem,6vw,4.5rem); line-height: 1.0; letter-spacing: -.03em; color: var(--fg); text-shadow: 0 0 40px {accent}44; }}
        .statement-slide .stmt em {{ color: {accent}; font-style: normal; text-shadow: 0 0 30px {accent}; }}
    """,

    # ── 8. BROADSHEET ─────────────────────────────────────────────────────────
    # Screenshots: bold "80%" orange blocks + "Document" orange sidebar
    # Off-white, Archivo Black, bold color sidebar strip, loud numbers, Bloomberg energy
    "broadsheet": """
        :root {{
            --accent: {accent};
            --fg: #0f0f0f; --fg2: #3d3d3d; --bg: #f7f4ee;
            --surface: #ede9e0; --border: #0f0f0f; --dim: #888;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'IBM Plex Sans', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 3.5rem 4.5rem 3.5rem 7rem;
            display: flex; flex-direction: column; justify-content: flex-start;
            border-left: 5.5rem solid {accent};
        }}
        .reveal h1 {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(2.8rem,8vw,6rem); line-height: .86;
            letter-spacing: -.04em; text-transform: uppercase; color: var(--fg); margin: 0 0 .4em;
        }}
        .reveal h2 {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(1.4rem,3.2vw,2.2rem); line-height: .95;
            letter-spacing: -.03em; text-transform: uppercase; color: var(--fg); margin: 0 0 .85em;
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%; counter-reset: li; }}
        .reveal li {{
            counter-increment: li; padding: .75em 0;
            border-top: 2px solid var(--fg); font-size: .86em; line-height: 1.5; color: var(--fg);
            display: grid; grid-template-columns: 3rem 1fr; gap: 1rem; align-items: baseline;
        }}
        .reveal li:last-child {{ border-bottom: 2px solid var(--fg); }}
        .reveal li::before {{ content: counter(li); font-family: 'Archivo Black', sans-serif; font-size: 1.5em; line-height: .85; color: {accent}; font-weight: 900; }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 2px solid var(--fg); border-radius: 0; }}
        .reveal pre code {{ font-size: .7em; background: var(--surface); padding: 1em; line-height: 1.6; color: var(--fg); }}
        .reveal .progress {{ background: {accent}; height: 3px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; font-family: 'IBM Plex Mono', monospace; }}
        .subtitle {{ font-family: 'IBM Plex Sans', sans-serif; color: var(--fg2); font-size: .8em; margin-top: .4em; line-height: 1.4; }}
        .hero-metric {{
            font-family: 'Archivo Black', sans-serif; font-weight: 900;
            font-size: clamp(5rem,20vw,13rem); line-height: .8; color: {accent};
            letter-spacing: -.055em; display: block; text-transform: uppercase;
        }}
        .metric-label {{ font-family: 'IBM Plex Mono', monospace; font-size: .6em; letter-spacing: .16em; text-transform: uppercase; color: var(--dim); margin-bottom: .3em; }}
        .metric-desc {{ font-size: .8em; color: var(--fg2); margin-top: .45em; line-height: 1.4; border-left: 3px solid {accent}; padding-left: .8rem; }}
        .grid-card {{ border-top: 4px solid {accent}; padding-top: .9rem; background: transparent; }}
        .grid-card h4 {{ font-family: 'Archivo Black', sans-serif; font-size: .78rem; font-weight: 900; text-transform: uppercase; color: var(--fg); margin: 0 0 .3em; letter-spacing: -.01em; }}
        .grid-card p {{ font-size: .74rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-num {{ font-family: 'Archivo Black', sans-serif; font-size: 2rem; color: {accent}; font-weight: 900; display: block; margin-bottom: .3em; letter-spacing: -.03em; }}
        .section-divider {{
            display: flex; flex-direction: column; justify-content: center; flex: 1;
            margin-left: -3.5rem; padding-left: 3.5rem;
            background: {accent};
        }}
        .section-divider .sec-num {{ font-family: 'Archivo Black', sans-serif; font-weight: 900; font-size: clamp(7rem,24vw,16rem); line-height: .8; color: rgba(0,0,0,0.18); letter-spacing: -.06em; text-transform: uppercase; position: absolute; right: 2rem; top: 50%; transform: translateY(-50%); pointer-events: none; }}
        .section-divider .sec-label {{ font-family: 'IBM Plex Mono', monospace; font-size: .6em; letter-spacing: .22em; text-transform: uppercase; color: rgba(255,255,255,0.6); margin-bottom: .4rem; }}
        .section-divider .sec-title {{ font-family: 'Archivo Black', sans-serif; font-weight: 900; font-size: clamp(2.5rem,7vw,5.5rem); line-height: .88; text-transform: uppercase; color: #fff; margin: 0; letter-spacing: -.04em; }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{ font-family: 'Archivo Black', sans-serif; font-weight: 900; font-size: clamp(2.5rem,7vw,5.5rem); line-height: .88; text-transform: uppercase; color: var(--fg); letter-spacing: -.04em; }}
        .statement-slide .stmt em {{ color: {accent}; font-style: normal; }}
    """,

    # ── 9. OBSIDIAN ───────────────────────────────────────────────────────────
    # Screenshots: dark charcoal activation strategy with lime green circles + donut metrics
    # Dark charcoal, lime green accent, circular metric motif, dashboard energy
    "obsidian": """
        :root {{
            --accent: {accent};
            --fg: #e8ede8; --fg2: #8a9e8a; --bg: #111518;
            --surface: #1a1f1a; --border: #2a3028; --dim: #4a5a4a;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'Space Grotesk', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 3.5rem 4.5rem;
            display: flex; flex-direction: column; justify-content: flex-start;
        }}
        .reveal h1 {{
            font-family: 'Space Grotesk', sans-serif; font-weight: 700;
            font-size: clamp(2.8rem,8vw,5.5rem); line-height: .9;
            letter-spacing: -.04em; color: var(--fg); margin: 0 0 .4em;
        }}
        .reveal h2 {{
            font-family: 'Space Grotesk', sans-serif; font-weight: 600;
            font-size: clamp(1.3rem,3vw,2rem); line-height: 1.1;
            letter-spacing: -.025em; color: var(--fg); margin: 0 0 .85em;
            display: flex; align-items: center; gap: .8rem;
        }}
        .reveal h2::before {{ content: ""; display: inline-block; width: .7rem; height: .7rem; background: {accent}; border-radius: 50%; flex-shrink: 0; }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%;
            display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; align-content: start; counter-reset: li; }}
        .reveal li {{
            counter-increment: li; background: var(--surface); border: 1px solid var(--border);
            border-radius: 8px; padding: 1rem 1.1rem;
            font-size: .84em; line-height: 1.5; color: var(--fg);
            display: grid; grid-template-columns: 2rem 1fr; gap: .7rem; align-items: baseline;
        }}
        .reveal li::before {{ content: counter(li, decimal-leading-zero); color: {accent}; font-size: .8em; font-weight: 600; }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 1px solid var(--border); border-radius: 6px; }}
        .reveal pre code {{ font-size: .7em; background: var(--surface); padding: 1em; line-height: 1.6; }}
        .reveal .progress {{ background: {accent}; height: 2px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; }}
        .subtitle {{ color: var(--fg2); font-size: .78em; margin-top: .35em; line-height: 1.4; }}
        .hero-metric {{
            font-family: 'Space Grotesk', sans-serif; font-weight: 700;
            font-size: clamp(5rem,18vw,10rem); line-height: .86; color: {accent};
            letter-spacing: -.05em; display: block; position: relative;
        }}
        /* Circular accent ring behind metric */
        .hero-metric::before {{
            content: ""; position: absolute;
            width: clamp(4rem,14vw,8rem); height: clamp(4rem,14vw,8rem);
            border: 4px solid {accent}; border-radius: 50%;
            left: -.2em; top: .05em; opacity: .3;
        }}
        .metric-label {{ font-size: .6em; letter-spacing: .18em; text-transform: uppercase; color: var(--dim); margin-bottom: .35em; }}
        .metric-desc {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: .75rem 1rem; font-size: .76em; color: var(--fg2); margin-top: .5em; line-height: 1.5; }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; border-top: 2px solid {accent}; }}
        .grid-card h4 {{ font-size: .78rem; font-weight: 600; color: {accent}; margin: 0 0 .3em; }}
        .grid-card p {{ font-size: .72rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-step {{ border-top: none; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }}
        .t-step.fragment.visible {{ border-color: {accent}; }}
        .t-num {{ font-size: 2rem; font-weight: 700; color: {accent}; display: block; margin-bottom: .3em; }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; position: relative; }}
        .section-divider::before {{
            content: ""; position: absolute;
            width: clamp(10rem,35vw,22rem); height: clamp(10rem,35vw,22rem);
            border: 2px solid {accent}; border-radius: 50%;
            right: 2rem; top: 50%; transform: translateY(-50%); opacity: .12;
        }}
        .section-divider .sec-num {{ font-weight: 700; font-size: clamp(6rem,22vw,13rem); line-height: .85; color: {accent}; letter-spacing: -.05em; opacity: .55; }}
        .section-divider .sec-label {{ color: var(--dim); font-size: .6em; letter-spacing: .22em; text-transform: uppercase; margin: .3rem 0; display: flex; align-items: center; gap: .6rem; }}
        .section-divider .sec-label::before {{ content: ""; width: .6rem; height: .6rem; background: {accent}; border-radius: 50%; }}
        .section-divider .sec-title {{ font-weight: 600; font-size: clamp(1.8rem,5vw,3.5rem); line-height: .95; color: var(--fg); margin: 0; letter-spacing: -.02em; }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{ font-weight: 700; font-size: clamp(2rem,6vw,4.5rem); line-height: 1.0; letter-spacing: -.03em; color: var(--fg); }}
        .statement-slide .stmt em {{ color: {accent}; font-style: normal; }}
    """,

    # ── 10. KODACHROME ────────────────────────────────────────────────────────
    # Screenshots: mountain/nature photography overlays + real-estate warm tones
    # Warm vintage: cream/terracotta, italic DM Serif, photo-overlay slides, film-grain texture
    "kodachrome": """
        :root {{
            --accent: {accent};
            --fg: #1c1008; --fg2: #5c3d22; --bg: #faf5ee;
            --surface: #f2ead8; --border: #d4b896; --dim: #9a7a58;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'IBM Plex Sans', sans-serif; color: var(--fg); }}
        .reveal .slides section {{
            text-align: left; padding: 3.5rem 4.5rem;
            display: flex; flex-direction: column; justify-content: flex-start;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
        }}
        .reveal h1 {{
            font-family: 'DM Serif Display', serif; font-weight: 400; font-style: italic;
            font-size: clamp(3rem,8.5vw,6rem); line-height: .9;
            letter-spacing: -.03em; color: var(--fg); margin: 0 0 .4em;
        }}
        .reveal h1 em {{ color: {accent}; }}
        .reveal h2 {{
            font-family: 'DM Serif Display', serif; font-weight: 400;
            font-size: clamp(1.4rem,3.5vw,2.3rem); line-height: 1.08;
            letter-spacing: -.02em; color: var(--fg); margin: 0 0 .85em;
            border-bottom: 1px solid var(--border); padding-bottom: .35em;
        }}
        .reveal ul, .reveal ol {{ list-style: none; padding: 0; margin: 0; width: 100%; counter-reset: li; }}
        .reveal li {{
            counter-increment: li; padding: .65em 0;
            border-top: 1px solid var(--border); font-size: .86em; line-height: 1.55; color: var(--fg);
            display: grid; grid-template-columns: 2.8rem 1fr; gap: .9rem; align-items: baseline;
        }}
        .reveal li:last-child {{ border-bottom: 1px solid var(--border); }}
        .reveal li::before {{
            font-family: 'DM Serif Display', serif; font-style: italic;
            content: counter(li); font-size: 1.8em; line-height: .85; color: {accent};
        }}
        .reveal pre {{ width: 100%; margin: .5em 0; border: 1px solid var(--border); border-radius: 2px; }}
        .reveal pre code {{ font-size: .7em; background: var(--surface); padding: 1em; line-height: 1.6; color: var(--fg); }}
        .reveal .progress {{ background: {accent}; height: 2px; }}
        .reveal .controls {{ color: {accent}; }}
        .reveal .slide-number {{ color: var(--dim); font-size: .5em; }}
        .subtitle {{
            font-family: 'DM Serif Display', serif; font-style: italic;
            color: var(--fg2); font-size: .84em; margin-top: .4em; line-height: 1.4; max-width: 30ch;
        }}
        .hero-metric {{
            font-family: 'DM Serif Display', serif; font-style: italic; font-weight: 400;
            font-size: clamp(5rem,18vw,10rem); line-height: .82; color: {accent};
            letter-spacing: -.04em; display: block;
        }}
        .metric-label {{
            font-family: 'IBM Plex Mono', monospace; font-size: .6em; letter-spacing: .18em;
            text-transform: uppercase; color: var(--dim); margin-bottom: .35em;
        }}
        .metric-desc {{
            font-family: 'DM Serif Display', serif; font-style: italic;
            font-size: .82em; color: var(--fg2); margin-top: .5em; line-height: 1.45;
            border-left: 2px solid var(--border); padding-left: .9rem;
        }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); padding: 1rem; border-radius: 2px; }}
        .grid-card h4 {{ font-family: 'DM Serif Display', serif; font-size: .82rem; font-weight: 400; color: var(--fg); margin: 0 0 .3em; }}
        .grid-card p {{ font-family: 'DM Serif Display', serif; font-style: italic; font-size: .76rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .t-num {{ font-family: 'DM Serif Display', serif; font-style: italic; font-size: 2.2rem; color: {accent}; font-weight: 400; display: block; margin-bottom: .3em; }}
        .section-divider {{ display: flex; flex-direction: column; justify-content: center; flex: 1; position: relative; overflow: hidden; }}
        .section-divider .sec-num {{
            position: absolute; right: -1rem; top: 50%; transform: translateY(-50%);
            font-family: 'DM Serif Display', serif; font-style: italic; font-weight: 400;
            font-size: clamp(8rem,28vw,18rem); line-height: .8; color: {accent}; opacity: .12; letter-spacing: -.05em;
        }}
        .section-divider .sec-label {{
            font-family: 'IBM Plex Mono', monospace; font-size: .6em; letter-spacing: .22em;
            text-transform: uppercase; color: var(--dim); margin-bottom: .5rem;
        }}
        .section-divider .sec-title {{
            font-family: 'DM Serif Display', serif; font-weight: 400; font-style: italic;
            font-size: clamp(2.5rem,8vw,5.5rem); line-height: .9; letter-spacing: -.03em; color: var(--fg); margin: 0;
        }}
        .section-divider .sec-title em {{ color: {accent}; font-style: italic; }}
        .statement-slide {{ display: flex; flex-direction: column; justify-content: center; flex: 1; }}
        .statement-slide .stmt {{
            font-family: 'DM Serif Display', serif; font-weight: 400; font-style: italic;
            font-size: clamp(2.5rem,7vw,5.5rem); line-height: 1.0; letter-spacing: -.025em; color: var(--fg);
        }}
        .statement-slide .stmt em {{ color: {accent}; }}
    """,

    # ── LEGACY (kept for old saved projects) ─────────────────────────────────
    "dark-editorial": """
        :root {{
            --accent: {accent};
            --fg: #F0F0F0; --fg2: #A0A0B0; --bg: #0F0F14;
            --surface: #1A1A24; --border: #2A2A38; --dim: #606070;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: '{font_body}', 'Inter', sans-serif; color: var(--fg); text-align: left; }}
        .reveal .slides section {{
            text-align: left; padding: 3rem 4rem;
            display: flex; flex-direction: column; justify-content: flex-start;
        }}
        .reveal h1 {{ font-family: '{font_heading}', serif; font-size: clamp(2rem,5vw,3rem);
            font-weight: 400; line-height: 1.15; color: var(--fg); letter-spacing: -.02em; }}
        .reveal h2 {{ font-family: '{font_body}', sans-serif; font-size: clamp(1.2rem,3vw,1.75rem);
            font-weight: 600; color: var(--fg); border-left: 4px solid var(--accent);
            padding-left: .6em; margin-bottom: .8em; line-height: 1.25; }}
        .reveal ul, .reveal ol {{ text-align: left; padding-left: 1.4em; margin: 0; width: 100%; }}
        .reveal ul li, .reveal ol li {{ font-size: .88em; line-height: 1.65; margin: .35em 0; color: var(--fg); }}
        .reveal ul li::marker {{ color: var(--accent); }}
        .reveal pre {{ width: 100%; margin: 0; border-radius: 6px; border: 1px solid var(--border); }}
        .reveal pre code {{ font-size: .72em; background: var(--surface); padding: 1em; line-height: 1.6; }}
        .reveal .progress {{ background: var(--accent); height: 3px; }}
        .reveal .controls {{ color: var(--accent); }}
        .reveal .slide-number {{ color: var(--dim); font-size: .55em; }}
        .subtitle {{ color: var(--fg2); font-size: .8em; margin-top: .3em; }}
        .hero-metric {{ font-family: '{font_heading}', serif; font-size: clamp(4rem,15vw,7rem);
            color: var(--accent); line-height: 1; font-weight: 400; display: block; text-align: center; }}
        .metric-label {{ font-size: .68em; letter-spacing: .15em; text-transform: uppercase;
            color: var(--accent); text-align: center; margin-bottom: .4em; }}
        .metric-desc {{ font-size: .78em; color: var(--fg2); text-align: center; margin-top: .4em; }}
        .slide-split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; align-items: start; margin-top: 1rem; }}
        .slide-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; flex: 1; margin-top: .5rem; }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }}
        .grid-card h4 {{ font-size: .8rem; font-weight: 600; color: var(--accent); margin: 0 0 .3em; }}
        .grid-card p {{ font-size: .78rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .timeline-row {{ display: flex; gap: 0; margin-top: 1rem; flex: 1; }}
        .t-step {{ flex: 1; padding: 1rem; border-top: 3px solid var(--border); position: relative; }}
        .t-step.fragment.visible {{ border-top-color: var(--accent); }}
        .t-num {{ font-family: '{font_heading}', serif; font-size: 2rem; color: var(--accent);
            font-weight: 400; display: block; margin-bottom: .3em; }}
        .t-step p {{ font-size: .78rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
    """,
    "light-clean": """
        :root {{
            --accent: {accent};
            --fg: #1A1A2E; --fg2: #555570; --bg: #FAFAFA;
            --surface: #F0F0F5; --border: #DDDDE8; --dim: #999;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: '{font_body}', 'Inter', sans-serif; color: var(--fg); text-align: left; }}
        .reveal .slides section {{
            text-align: left; padding: 3rem 4rem;
            display: flex; flex-direction: column; justify-content: flex-start;
        }}
        .reveal h1 {{ font-family: '{font_heading}', sans-serif; font-size: clamp(2rem,5vw,3rem);
            font-weight: 700; color: var(--fg); letter-spacing: -.03em; }}
        .reveal h2 {{ font-family: '{font_body}', sans-serif; font-size: clamp(1.2rem,3vw,1.7rem);
            font-weight: 600; color: var(--fg); border-bottom: 2px solid var(--accent);
            padding-bottom: .25em; margin-bottom: .9em; }}
        .reveal ul, .reveal ol {{ text-align: left; padding-left: 1.4em; margin: 0; width: 100%; }}
        .reveal ul li, .reveal ol li {{ font-size: .88em; line-height: 1.7; margin: .3em 0; }}
        .reveal ul li::marker {{ color: var(--accent); }}
        .reveal pre code {{ font-size: .72em; background: var(--surface); border: 1px solid var(--border); padding: 1em; border-radius: 6px; line-height: 1.6; }}
        .reveal .progress {{ background: var(--accent); height: 3px; }}
        .reveal .controls {{ color: var(--accent); }}
        .reveal .slide-number {{ color: var(--dim); font-size: .55em; }}
        .subtitle {{ color: var(--fg2); font-size: .8em; }}
        .hero-metric {{ font-family: '{font_heading}', sans-serif; font-size: clamp(4rem,15vw,7rem);
            color: var(--accent); line-height: 1; font-weight: 700; display: block; text-align: center; }}
        .metric-label {{ font-size: .68em; letter-spacing: .15em; text-transform: uppercase; color: var(--accent); text-align: center; }}
        .metric-desc {{ font-size: .78em; color: var(--fg2); text-align: center; margin-top: .4em; }}
        .slide-split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; align-items: start; margin-top: 1rem; }}
        .slide-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; flex: 1; margin-top: .5rem; }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: .9rem; }}
        .grid-card h4 {{ font-size: .8rem; font-weight: 700; color: var(--accent); margin: 0 0 .25em; }}
        .grid-card p {{ font-size: .77rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .timeline-row {{ display: flex; gap: 0; margin-top: 1rem; flex: 1; }}
        .t-step {{ flex: 1; padding: .9rem; border-top: 3px solid var(--border); }}
        .t-step.fragment.visible {{ border-top-color: var(--accent); }}
        .t-num {{ font-family: '{font_heading}', sans-serif; font-size: 2rem; color: var(--accent); font-weight: 700; display: block; margin-bottom: .25em; }}
        .t-step p {{ font-size: .77rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
    """,
    "bold-gradient": """
        :root {{
            --accent: {accent};
            --fg: #FFFFFF; --fg2: rgba(255,255,255,.65); --bg-a: #0D0D1A; --bg-b: #1A0A2E;
            --surface: rgba(255,255,255,.07); --border: rgba(255,255,255,.12); --dim: rgba(255,255,255,.35);
        }}
        .reveal-viewport {{ background: linear-gradient(135deg, var(--bg-a), var(--bg-b)); }}
        .reveal {{ font-family: '{font_body}', 'Inter', sans-serif; color: var(--fg); text-align: left; }}
        .reveal .slides section {{
            text-align: left; padding: 3rem 4rem;
            display: flex; flex-direction: column; justify-content: flex-start;
        }}
        .reveal h1 {{ font-family: '{font_heading}', sans-serif; font-size: clamp(2rem,5vw,3rem);
            font-weight: 800; color: #fff; letter-spacing: -.03em; text-shadow: 0 0 60px {accent}44; }}
        .reveal h2 {{ font-family: '{font_body}', sans-serif; font-size: clamp(1.2rem,3vw,1.7rem);
            font-weight: 700; color: #fff; border-left: 4px solid var(--accent);
            padding-left: .6em; margin-bottom: .8em; }}
        .reveal ul, .reveal ol {{ text-align: left; padding-left: 1.4em; margin: 0; width: 100%; }}
        .reveal ul li, .reveal ol li {{ font-size: .88em; line-height: 1.65; margin: .35em 0; }}
        .reveal ul li::marker {{ color: var(--accent); }}
        .reveal pre code {{ font-size: .72em; background: rgba(0,0,0,.4); border: 1px solid var(--border); padding: 1em; border-radius: 6px; line-height: 1.6; }}
        .reveal .progress {{ background: var(--accent); height: 3px; }}
        .reveal .controls {{ color: var(--accent); }}
        .reveal .slide-number {{ color: var(--dim); font-size: .55em; }}
        .subtitle {{ color: var(--fg2); font-size: .8em; }}
        .hero-metric {{ font-family: '{font_heading}', sans-serif; font-size: clamp(4rem,18vw,9rem);
            color: var(--accent); line-height: 1; font-weight: 800; display: block; text-align: center;
            text-shadow: 0 0 80px {accent}66; }}
        .metric-label {{ font-size: .68em; letter-spacing: .2em; text-transform: uppercase; color: var(--accent); text-align: center; }}
        .metric-desc {{ font-size: .78em; color: var(--fg2); text-align: center; margin-top: .4em; }}
        .slide-split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; align-items: start; margin-top: 1rem; }}
        .slide-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; flex: 1; margin-top: .5rem; }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }}
        .grid-card h4 {{ font-size: .8rem; font-weight: 700; color: var(--accent); margin: 0 0 .3em; }}
        .grid-card p {{ font-size: .77rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .timeline-row {{ display: flex; gap: 0; margin-top: 1rem; flex: 1; }}
        .t-step {{ flex: 1; padding: 1rem; border-top: 3px solid var(--border); }}
        .t-step.fragment.visible {{ border-top-color: var(--accent); }}
        .t-num {{ font-family: '{font_heading}', sans-serif; font-size: 2.2rem; color: var(--accent); font-weight: 800; display: block; margin-bottom: .3em; }}
        .t-step p {{ font-size: .77rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
    """,
    "minimal-mono": """
        :root {{
            --accent: {accent};
            --fg: #E8E8E8; --fg2: #888; --bg: #111111;
            --surface: #1C1C1C; --border: #2E2E2E; --dim: #555;
        }}
        .reveal-viewport {{ background: var(--bg); }}
        .reveal {{ font-family: 'JetBrains Mono', '{font_body}', monospace; color: var(--fg); text-align: left; font-size: .9rem; }}
        .reveal .slides section {{
            text-align: left; padding: 3rem 4rem;
            display: flex; flex-direction: column; justify-content: flex-start;
        }}
        .reveal h1 {{ font-family: 'JetBrains Mono', monospace; font-size: clamp(1.6rem,4vw,2.4rem);
            font-weight: 600; color: var(--fg); letter-spacing: -.01em; }}
        .reveal h1::before {{ content: "# "; color: var(--accent); }}
        .reveal h2 {{ font-family: 'JetBrains Mono', monospace; font-size: clamp(1rem,2.5vw,1.5rem);
            font-weight: 500; color: var(--fg); margin-bottom: .9em; }}
        .reveal h2::before {{ content: "## "; color: var(--accent); }}
        .reveal ul, .reveal ol {{ text-align: left; padding-left: 1.4em; margin: 0; list-style: none; width: 100%; }}
        .reveal ul li::before {{ content: "→ "; color: var(--accent); }}
        .reveal ul li, .reveal ol li {{ font-size: .82em; line-height: 1.7; margin: .3em 0; }}
        .reveal pre code {{ font-size: .72em; background: var(--surface); border: 1px solid var(--border); padding: 1em; border-radius: 3px; line-height: 1.6; }}
        .reveal .progress {{ background: var(--accent); height: 2px; }}
        .reveal .controls {{ color: var(--accent); }}
        .reveal .slide-number {{ color: var(--dim); font-size: .55em; }}
        .subtitle {{ color: var(--fg2); font-size: .78em; }}
        .hero-metric {{ font-family: 'JetBrains Mono', monospace; font-size: clamp(4rem,14vw,7rem);
            color: var(--accent); line-height: 1; font-weight: 600; display: block; text-align: center; }}
        .metric-label {{ font-size: .65em; letter-spacing: .15em; text-transform: uppercase; color: var(--dim); text-align: center; }}
        .metric-desc {{ font-size: .75em; color: var(--fg2); text-align: center; margin-top: .4em; font-family: 'JetBrains Mono', monospace; }}
        .slide-split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; align-items: start; margin-top: 1rem; }}
        .slide-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; flex: 1; margin-top: .5rem; }}
        .grid-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 3px; padding: .9rem; }}
        .grid-card h4 {{ font-size: .75rem; font-weight: 600; color: var(--accent); margin: 0 0 .3em; font-family: 'JetBrains Mono', monospace; }}
        .grid-card p {{ font-size: .75rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
        .timeline-row {{ display: flex; gap: 0; margin-top: 1rem; flex: 1; }}
        .t-step {{ flex: 1; padding: .9rem; border-top: 2px solid var(--border); }}
        .t-step.fragment.visible {{ border-top-color: var(--accent); }}
        .t-num {{ font-family: 'JetBrains Mono', monospace; font-size: 1.8rem; color: var(--accent); font-weight: 600; display: block; margin-bottom: .3em; }}
        .t-step p {{ font-size: .75rem; color: var(--fg2); margin: 0; line-height: 1.5; }}
    """,
}

# Theme aliases — map legacy and shorthand names to canonical ones
_THEME_ALIASES = {
    "dark-editorial":  "obsidian",
    "dark-gradient":   "obsidian",
    "dracula":         "obsidian",
    "minimal-mono":    "obsidian",
    "minimal":         "obsidian",
    "terminal-brutalist": "obsidian",
    "light-clean":     "editorial-press",
    "light":           "editorial-press",
    "bold-gradient":   "gradient-dreamscape",
}

_DEFAULT_THEME_CONFIG = {
    "theme":        "editorial-press",
    "accent_color": "#b8331f",
    "font_heading": "DM Serif Display",
    "font_body":    "IBM Plex Sans",
}

# Font registry (all loaded via _ALL_FONTS_URL; kept for designer agent hints)
_FONT_URLS = {
    "DM Serif Display":    "family=DM+Serif+Display:ital@0;1",
    "Instrument Serif":    "family=Instrument+Serif:ital@0;1",
    "Barlow Condensed":    "family=Barlow+Condensed:wght@300;500;700;900",
    "Archivo Black":       "family=Archivo+Black",
    "Space Grotesk":       "family=Space+Grotesk:wght@300;400;500;600;700",
    "IBM Plex Sans":       "family=IBM+Plex+Sans:wght@300;400;500;700",
    "IBM Plex Mono":       "family=IBM+Plex+Mono:wght@300;400;500;600",
    "Space Mono":          "family=Space+Mono:wght@400;700",
    "JetBrains Mono":      "family=JetBrains+Mono:wght@400;500;700;800",
}


def _build_theme_css(theme_config: dict) -> str:
    """Fill theme skeleton with accent color and font choices from designer agent."""
    theme = theme_config.get("theme", "editorial-press")
    theme = _THEME_ALIASES.get(theme, theme)
    if theme not in _THEME_SKELETONS:
        theme = "editorial-press"
    skeleton = _THEME_SKELETONS[theme]
    return skeleton.format(
        accent=theme_config.get("accent_color", "#b8331f"),
        font_heading=theme_config.get("font_heading", "DM Serif Display"),
        font_body=theme_config.get("font_body", "IBM Plex Sans"),
    ) + _SHARED_CLASSES.format(
        accent=theme_config.get("accent_color", "#b8331f"),
        font_heading=theme_config.get("font_heading", "DM Serif Display"),
        font_body=theme_config.get("font_body", "IBM Plex Sans"),
    )


def _build_font_url(theme_config: dict) -> str:
    return _ALL_FONTS_URL


def _assemble(title: str, slides_html: list[str],
              theme: "str | dict" = "dark-editorial") -> str:
    # Accept either a legacy string theme name or a full theme_config dict
    if isinstance(theme, str):
        tc = dict(_DEFAULT_THEME_CONFIG)
        tc["theme"] = _THEME_ALIASES.get(theme, theme)
    else:
        tc = {**_DEFAULT_THEME_CONFIG, **theme}

    theme_css  = _build_theme_css(tc)
    font_url   = _build_font_url(tc)
    slides_joined = "\n".join(slides_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{font_url}" rel="stylesheet">
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
  slideNumber: 'c/t',
  transition: 'fade',
  transitionSpeed: 'fast',
  autoAnimateEasing: 'ease-out',
  autoAnimateDuration: 0.5,
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
    theme: str = "",
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

    # ═══════════════════════════════════════════════════════════════
    # AGENTIC PIPELINE
    #   0  CSV Chart Agent  — pre-render CSVs so planner can see them
    #   0.5 Designer Agent  — theme + accent + fonts
    #   1   Vision Agent    — describe existing images
    #   2   Planner Agent   — outline with visual_type/visual_prompt per slide
    #   3   Visual Agent    — python_chart → matplotlib, ai_image → API
    #   4   Coder Agent     — render each slide to HTML
    # ═══════════════════════════════════════════════════════════════

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

    # Stage 0.5 — Designer Agent (theme + accent + fonts)
    # If the user explicitly set a theme via 'sarathi theme --set X', honour it.
    # The designer agent then only picks accent colour and fonts, not the theme name.
    console.print("[dim][sarathi] Stage 0.5 — Designer Agent[/dim]")
    _legacy = {"dark-gradient", "dark-editorial", "dracula", "light", "light-clean",
               "bold-gradient", "minimal", "minimal-mono"}
    _user_theme = theme if (theme and theme not in _legacy) else None
    theme_config = _designer_agent(
        project_name, domain, description, all_files, _planner, console, verbose,
        forced_theme=_user_theme,
    )
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

    # Stage 3 — Visual Agent (python_chart + ai_image dispatch based on planner decisions)
    console.print("[dim][sarathi] Stage 3 — Visual Agent[/dim]")
    py_count = sum(1 for s in outline.get("slides", []) if s.get("visual_type") == "python_chart")
    ai_count = sum(1 for s in outline.get("slides", []) if s.get("visual_type") == "ai_image")
    if py_count or ai_count:
        new_arts = _visual_agent(
            outline, artifacts_map, _coder, project_dir, theme_config,
            image_gen_model if image_gen_enabled else "",
            cloud_api_url, cloud_api_key, console, verbose=verbose,
        )
        artifacts_map.update(new_arts)
    else:
        console.print("  [dim]Visual Agent: no python_chart or ai_image slides in outline[/dim]")
    console.print()

    # Stage 4 — Coder Agent
    console.print("[dim][sarathi] Stage 4 — Coder Agent[/dim]")
    console.print(f"  Model: [bold]{_coder}[/bold]")
    slides = outline.get("slides", [])
    slides_html: list[str] = []
    n = len(slides)
    t_gen = time.perf_counter()
    repairs = 0

    for i, slide in enumerate(slides, 1):
        heading = slide.get("heading", f"Slide {slide.get('id', '')}")
        console.print(f"  Slide {i}/{n} — [bold]{heading[:60]}[/bold]")
        try:
            html = _render_slide(slide, artifacts_map, _coder, verbose=verbose)
            # Critique Agent — one repair pass if rubric fails
            failures = _critique_slide(html, slide)
            if failures:
                repair_msg = (
                    _coder_user(slide, artifacts_map) +
                    "\n\n<Critique>\nFix these issues:\n" +
                    "\n".join(f"- {f}" for f in failures) +
                    "\n</Critique>\n\nRepair the slide now."
                )
                try:
                    html = _extract_section(
                        _chat(_coder, _CODER_SYSTEM, repair_msg, verbose=verbose)
                    )
                    repairs += 1
                except Exception:
                    pass  # keep original if repair fails
        except Exception as exc:
            html = (
                f"<section><h2>{heading}</h2>"
                f"<p style='color:var(--accent,#f48fb1)'>Render error: {exc}</p></section>"
            )
        slides_html.append(html)

    duration_s = time.perf_counter() - t_gen
    repair_note = f", {repairs} critique repair(s)" if repairs else ""
    console.print(f"  [green]✓ All {len(slides_html)} slides rendered{repair_note}.[/green]")
    console.print()

    # ── Assemble ───────────────────────────────────────────────────────────────
    html_doc = _assemble(outline.get("title", project_name), slides_html, theme_config)
    output_html.write_text(html_doc, encoding="utf-8")

    for s in outline.get("slides", []):
        s["_theme"] = theme_config.get("theme", "dark-editorial")
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
        "theme":       theme_config.get("theme", "dark-editorial"),
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

_DESIGNER_SYSTEM = """\
You are a presentation art director. Given a project description and domain, choose the best
visual theme for a slide deck. Output ONLY a valid JSON object — no prose, no markdown fences.

Theme options:
  terminal-brutalist  — near-black bg, JetBrains Mono everywhere, terminal-green accent,
                        scanline texture, build-log chrome. Ideal: dev tools, infra, CLI, systems.
  editorial-press     — cream bg, DM Serif Display, scarlet accent, masthead header,
                        magazine spread layout. Ideal: engineering reviews, quarterly reports, research.
  gradient-dreamscape — deep purple bg with gradient mesh, Instrument Serif italic,
                        glass cards, gradient text fills. Ideal: keynotes, AI/ML, startup demos.
  blueprint           — navy bg with cyan engineering grid, Barlow Condensed 900,
                        amber dimension lines, corner marks. Ideal: architecture, data pipelines, infra.
  swiss-brutalism     — warm white bg, Archivo Black, hard black rules, single electric accent circle.
                        Ideal: product pitches, company reviews, high-contrast bold statements.
  harvest             — dark forest green bg, orange accent, bold Barlow Condensed, photography-ready.
                        Ideal: product launches, sustainability, bold growth narrative.
  neon-noir           — near-black bg, electric blue/cyan glow, glowing borders, futuristic SaaS.
                        Ideal: AI products, cloud infra, developer platforms, investor demos.
  broadsheet          — off-white bg, Archivo Black, bold accent sidebar strip, huge numbers.
                        Ideal: business reviews, market analysis, investor updates, bold data stories.
  obsidian            — dark charcoal bg, lime green accent, circular motifs, dashboard feel.
                        Ideal: analytics, OKR reviews, product metrics, activation dashboards.
  kodachrome          — warm cream bg, terracotta accent, italic DM Serif, film-grain texture.
                        Ideal: case studies, team presentations, creative projects, storytelling.

Accent color options (pick ONE that fits the project energy):
  #00ff9c  terminal green — hacker, systems, infrastructure
  #b8331f  scarlet        — authority, editorial, data journalism
  #d946ef  vivid purple   — AI, generative, cutting-edge ML
  #ffb84d  amber          — engineering, precision, technical drawing
  #ff3d2e  electric red   — bold, urgent, product-first
  #06b6d4  cyan           — data, analytics, technical precision
  #f59e0b  gold           — premium, achievement, business metrics
  #4ade80  green          — growth, success, deployment

Font heading options (pick based on theme):
  terminal-brutalist  → JetBrains Mono
  editorial-press     → DM Serif Display
  gradient-dreamscape → Instrument Serif
  blueprint           → Barlow Condensed
  swiss-brutalism     → Archivo Black
  harvest             → Barlow Condensed
  neon-noir           → Space Grotesk
  broadsheet          → Archivo Black
  obsidian            → Space Grotesk
  kodachrome          → DM Serif Display

Font body options:
  terminal-brutalist  → JetBrains Mono
  editorial-press     → IBM Plex Sans
  gradient-dreamscape → Space Grotesk
  blueprint           → IBM Plex Mono
  swiss-brutalism     → Space Grotesk
  harvest             → IBM Plex Sans
  neon-noir           → Space Grotesk
  broadsheet          → IBM Plex Sans
  obsidian            → Space Grotesk
  kodachrome          → IBM Plex Sans

Output schema:
{
  "theme": "terminal-brutalist | editorial-press | gradient-dreamscape | blueprint | swiss-brutalism | harvest | neon-noir | broadsheet | obsidian | kodachrome",
  "accent_color": "#XXXXXX",
  "accent_color_name": "name",
  "font_heading": "one of the heading options above",
  "font_body": "one of the body options above",
  "reasoning": "one sentence explaining the choice"
}
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


def _designer_agent(
    project_name: str,
    domain: str,
    description: str,
    files: "list[ResultFile]",
    model: str,
    console,
    verbose: bool = False,
    forced_theme: "str | None" = None,
) -> dict:
    """Choose theme, accent colour, and fonts for this deck. Returns theme_config dict.

    If forced_theme is set (user ran 'sarathi theme --set X'), the LLM only picks
    accent colour and fonts — the theme name is locked in.
    """
    file_types = list({f.type for f in files})

    if forced_theme:
        # User explicitly chose a theme — only ask the LLM for accent + fonts
        system = _DESIGNER_SYSTEM + (
            f"\n\nCRITICAL: The user has locked the theme to \"{forced_theme}\". "
            f"You MUST output \"theme\": \"{forced_theme}\" exactly. "
            f"Only choose accent_color, font_heading, and font_body."
        )
        user_msg = (
            f"Project: {project_name}\n"
            f"Domain: {domain}\n"
            f"Description: {description[:300]}\n"
            f"Files present: {', '.join(file_types)}\n"
            f"Theme is locked to: {forced_theme}\n\n"
            f"Choose accent_color and fonts that work well with the {forced_theme} theme."
        )
    else:
        system = _DESIGNER_SYSTEM
        user_msg = (
            f"Project: {project_name}\n"
            f"Domain: {domain}\n"
            f"Description: {description[:300]}\n"
            f"Files present: {', '.join(file_types)}\n\n"
            "Choose the best visual theme for this project's slide deck."
        )

    try:
        raw = _chat(model, system, user_msg, verbose=verbose)
        tc  = _extract_json(raw)
        if forced_theme:
            tc["theme"] = forced_theme  # hard-enforce regardless of LLM output
        if tc.get("theme") and tc.get("accent_color"):
            locked = " [dim](theme locked by user)[/dim]" if forced_theme else ""
            console.print(
                f"  [green]✓ Designer Agent:[/green] "
                f"{tc['theme']} / {tc.get('accent_color_name', tc['accent_color'])} / "
                f"{tc.get('font_heading','?')} + {tc.get('font_body','?')}"
                + (f" — {tc['reasoning']}" if tc.get('reasoning') else "")
                + locked
            )
            return tc
    except Exception as exc:
        if verbose:
            console.print(f"  [dim]Designer Agent fallback ({exc})[/dim]")

    # Fallback: domain-based defaults (or forced theme with domain-matched accent)
    defaults = {
        "ml":       {"theme": "gradient-dreamscape", "accent_color": "#d946ef", "font_heading": "Instrument Serif", "font_body": "Space Grotesk"},
        "software": {"theme": "neon-noir",           "accent_color": "#1d4ed8", "font_heading": "Space Grotesk",    "font_body": "Space Grotesk"},
        "data":     {"theme": "blueprint",           "accent_color": "#ffb84d", "font_heading": "Barlow Condensed", "font_body": "IBM Plex Mono"},
        "diff":     {"theme": "editorial-press",     "accent_color": "#b8331f", "font_heading": "DM Serif Display", "font_body": "IBM Plex Sans"},
    }
    tc = dict(defaults.get(domain, defaults["ml"]))
    if forced_theme:
        tc["theme"] = forced_theme
    console.print(
        f"  [dim]Designer Agent:[/dim] fallback → {tc['theme']} / {tc['accent_color']}"
        + (" (theme locked)" if forced_theme else "")
    )
    return tc


def _visual_agent(
    outline: dict,
    artifacts_map: "dict[str, ResultFile]",
    model: str,
    project_dir: "Path",
    theme_config: dict,
    image_gen_model: str,
    cloud_api_url: str,
    cloud_api_key: str,
    console,
    verbose: bool = False,
) -> "dict[str, ResultFile]":
    """Post-planner visual generation: dispatch python_chart and ai_image slides.

    Reads visual_type / visual_prompt from each slide in the outline and:
      - python_chart → LLM writes matplotlib code → executed locally
      - ai_image     → calls image gen API with the specific visual_prompt
      - existing_file / none → no action
    """
    from . import viz as viz_module

    new_artifacts: dict[str, ResultFile] = {}
    accent = theme_config.get("accent_color", "#6C8EF5")
    viz_dir = project_dir / ".sarathi" / "viz"
    viz_dir.mkdir(parents=True, exist_ok=True)

    py_slides  = [s for s in outline.get("slides", []) if s.get("visual_type") == "python_chart"]
    ai_slides  = [s for s in outline.get("slides", []) if s.get("visual_type") == "ai_image"]

    # ── Python chart generation ───────────────────────────────────────────────
    if py_slides:
        console.print(f"  [dim]Visual Agent:[/dim] rendering {len(py_slides)} python_chart(s)...")

    for slide in py_slides:
        prompt = slide.get("visual_prompt", "")
        if not prompt:
            continue
        # Gather any CSV data the slide references as context
        data_snippets = []
        for art_path in slide.get("artifacts", []):
            rf = _lookup_artifact(art_path, artifacts_map)
            if rf and rf.type == "data":
                data_snippets.append(rf.content[:1200])

        def _chat_for_viz(system: str, user: str) -> str:
            return _chat(model, system, user, verbose=verbose)

        rf = viz_module.render_from_prompt(
            description=prompt,
            data_snippets=data_snippets,
            accent=accent,
            viz_dir=viz_dir,
            chat_fn=_chat_for_viz,
        )
        if rf:
            new_artifacts[rf.path] = rf
            slide.setdefault("artifacts", []).insert(0, rf.path)
            console.print(
                f"  [green]✓ Chart:[/green] slide {slide.get('id')} — "
                f"{slide.get('heading', '')[:55]}"
            )
        else:
            console.print(
                f"  [yellow]⚠ Chart failed:[/yellow] slide {slide.get('id')} — "
                f"will render as text"
            )

    # ── AI image generation ───────────────────────────────────────────────────
    if ai_slides and image_gen_model and cloud_api_url and cloud_api_key:
        ai_slides = ai_slides[:2]  # enforce max 2 per deck
        console.print(f"  [dim]Visual Agent:[/dim] generating {len(ai_slides)} ai_image(s) via {image_gen_model}...")

        from openai import OpenAI
        from . import keystore as _ks
        client = OpenAI(api_key=_ks.decrypt(cloud_api_key), base_url=cloud_api_url)

        for slide in ai_slides:
            visual_prompt = slide.get("visual_prompt", "")
            if not visual_prompt:
                visual_prompt = (
                    f"Technical illustration: {slide.get('heading', '')}. "
                    f"{slide.get('insight', '')[:200]}. "
                    "Clean minimal style, dark background, professional presentation graphic."
                )
            try:
                resp = client.images.generate(
                    model=image_gen_model,
                    prompt=visual_prompt,
                    size="1024x576",
                    response_format="b64_json",
                    n=1,
                )
                b64 = resp.data[0].b64_json
                key = f"_ai_img_{slide['id']}"
                rf  = ResultFile(path=key, filename=f"{key}.png",
                                 type="image", content=f"data:image/png;base64,{b64}")
                new_artifacts[key] = rf
                slide.setdefault("artifacts", []).insert(0, key)
                console.print(
                    f"  [green]✓ AI image:[/green] slide {slide.get('id')} — "
                    f"{slide.get('heading', '')[:55]}"
                )
            except Exception as exc:
                console.print(
                    f"  [yellow]⚠ AI image failed:[/yellow] slide {slide.get('id')} "
                    f"({exc.__class__.__name__})"
                )
    elif ai_slides and not (image_gen_model and cloud_api_url and cloud_api_key):
        console.print(
            f"  [dim]Visual Agent:[/dim] {len(ai_slides)} ai_image slide(s) skipped "
            f"— no image gen API configured"
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

    # Bullet slides — use the planner's bullet_points directly
    if stype in ("context", "takeaways", "next_steps") and bullets:
        items = "\n".join(f'    <li class="fragment">{b}</li>' for b in bullets[:3])
        return (
            '<section data-auto-animate>\n'
            f'  <h2>{heading}</h2>\n'
            '  <ul style="text-align:left">\n'
            f'{items}\n'
            '  </ul>\n'
            f'  <aside class="notes">{notes}</aside>\n'
            '</section>'
        )

    # Feature grid — 2×2 or 2×3 card layout for 3-6 discrete items
    if stype == "feature_grid" and bullets:
        cards = "\n".join(
            '<div class="grid-card fragment">'
            f'<h4>{b.split(":", 1)[0].strip() if ":" in b else b[:40]}</h4>'
            f'<p>{b.split(":", 1)[1].strip() if ":" in b else ""}</p>'
            '</div>'
            for b in bullets[:6]
        )
        return (
            '<section data-auto-animate>\n'
            f'  <h2>{heading}</h2>\n'
            f'  <div class="slide-grid">\n{cards}\n  </div>\n'
            f'  <aside class="notes">{notes}</aside>\n'
            '</section>'
        )

    # Timeline — horizontal process steps
    if stype == "timeline" and bullets:
        steps = "\n".join(
            f'<div class="t-step fragment">'
            f'<span class="t-num">{i + 1}</span>'
            f'<p>{b}</p>'
            f'</div>'
            for i, b in enumerate(bullets[:5])
        )
        return (
            '<section data-auto-animate>\n'
            f'  <h2>{heading}</h2>\n'
            f'  <div class="timeline-row">\n{steps}\n  </div>\n'
            f'  <aside class="notes">{notes}</aside>\n'
            '</section>'
        )

    # Section divider — big section number + title
    if stype == "section_divider":
        desc = bullets[0] if bullets else (insight[:160] if insight else "")
        num  = str(slide.get("id", "")).zfill(2)
        return (
            '<section data-auto-animate>\n'
            '  <div class="section-divider">\n'
            f'    <span class="sec-num">{num}</span>\n'
            f'    <p class="sec-label">Section {num}</p>\n'
            f'    <h2 class="sec-title">{heading}</h2>\n'
            + (f'    <p class="subtitle">{desc}</p>\n' if desc else '')
            + '  </div>\n'
            f'  <aside class="notes">{notes}</aside>\n'
            '</section>'
        )

    # Statement — one big bold claim, no bullets
    if stype == "statement":
        return (
            '<section data-auto-animate>\n'
            '  <div class="statement-slide">\n'
            f'    <p class="stmt">{heading}</p>\n'
            + (f'    <p class="subtitle">{insight[:180]}</p>\n' if insight else '')
            + '  </div>\n'
            f'  <aside class="notes">{notes}</aside>\n'
            '</section>'
        )

    return None  # code, comparison, table go to LLM


def _critique_slide(html: str, slide: dict) -> "list[str]":
    """Fast Python rubric check. Returns list of failures (empty = pass)."""
    failures = []
    heading = slide.get("heading", "")
    words   = heading.split()

    # 1. Heading is a label: < 5 words and no action verb
    action_verbs = {"is","are","was","were","has","have","shows","reveals","achieves",
                    "cuts","reduces","improves","increases","reaches","demonstrates",
                    "enables","delivers","eliminates","outperforms","surpasses"}
    if len(words) < 5 and not any(w.lower() in action_verbs for w in words):
        failures.append("Heading is a label, not a conclusion (add a finding or result)")

    # 2. Too many bullets
    if html.count("<li") > 4:
        failures.append(f"Too many bullets ({html.count('<li')} > 4 max)")

    # 3. Visual slide missing visual anchor
    stype = slide.get("type", "")
    if stype in ("image", "chart", "metric_callout"):
        if "<img" not in html and "hero-metric" not in html:
            failures.append("Visual slide missing image or metric callout element")

    # 4. Code dump
    if "<pre>" in html:
        m = re.search(r"<pre>(.*?)</pre>", html, re.DOTALL)
        if m and m.group(1).count("\n") > 20:
            failures.append("Code block > 20 lines (trim to key lines only)")

    return failures


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
