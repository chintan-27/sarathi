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
You are a presentation architect. Your ONLY job is to output a valid JSON outline for a \
Reveal.js presentation. Output NOTHING except the JSON object.

The JSON must match this exact schema:
{
  "title": "string",
  "domain": "string",
  "hero_metric": "string or null",
  "slides": [
    {
      "id": 1,
      "type": "title|context|metric_callout|chart|image|code|comparison|takeaways|next_steps",
      "heading": "string",
      "artifacts": ["relative/path/to/file"],
      "insight": "1-2 sentences: WHAT this slide shows AND WHY it matters",
      "speaker_notes": "2-3 sentences of speaker notes",
      "layout_hint": "optional: r-fit-text | r-stretch | r-stack | auto-animate"
    }
  ]
}

Rules:
- 8 to 12 slides total
- First slide type must be "title"
- Include exactly one "takeaways" slide near the end
- For metric_callout slides: set layout_hint to "r-fit-text"
- For chart/image slides: set layout_hint to "r-stretch"
- Assign artifacts only from the provided file list
- The insight field must interpret significance, not just describe
"""


def _planner_user(project_name: str, description: str, domain: str,
                  files: list[ResultFile]) -> str:
    dc = _DOMAIN_CONFIG.get(domain, _DOMAIN_CONFIG["ml"])
    file_list = "\n".join(f"  - [{f.type}] {f.path}" for f in files)

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
        f"</ProjectContext>\n\n"
        f"<ArtifactList>\n{file_list}\n</ArtifactList>\n\n"
        f"Generate the JSON outline now."
    )


# ── Pass 2: Coder prompt ──────────────────────────────────────────────────────

_CODER_SYSTEM = """\
You are a Reveal.js HTML expert. Generate a single <section> element for one slide.

Output ONLY this structure — nothing else:
<html_code>
<section ...>
  ...slide content...
  <aside class="notes">speaker notes here</aside>
</section>
</html_code>

Reveal.js layout rules:
- metric_callout → <h2 class="r-fit-text">THE NUMBER</h2> with a subtitle below
- chart or image → <img class="r-stretch" src="DATA_URI"> — the image fills the slide
- comparison/before-after → <div class="r-stack"> with fragment divs
- code slide → add data-auto-animate to the <section> tag
- Any slide in a sequence with the previous → add data-auto-animate to <section>

Style rules (CSS is injected globally — do NOT add <style> tags):
- Use semantic HTML: <h2> for heading, <p> for body, <ul><li> for bullets
- Max 5 bullet points per slide
- For code: use <pre><code class="language-python"> (or appropriate language)
- Embed images as <img src="DATA_URI_HERE"> — use the exact data URI provided

The insight must be woven into the slide text — do NOT just list data, EXPLAIN significance.
Speaker notes in <aside class="notes"> must be 2–3 sentences expanding on the slide.
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
) -> None:
    from . import viz as viz_module

    # Pre-render CSVs to chart images
    viz_files = viz_module.process(files, project_dir)
    all_files = files + viz_files

    # Build artifacts lookup
    artifacts_map: dict[str, ResultFile] = {rf.path: rf for rf in all_files}
    # Also index by filename for loose matching
    for rf in all_files:
        artifacts_map[rf.filename] = rf

    domain = domain_override or detect_domain(description, files)

    # Pass 1: generate or load outline
    if outline_path and outline_path.exists():
        outline = json.loads(outline_path.read_text(encoding="utf-8"))
    else:
        outline = _generate_outline(project_name, description, domain, all_files, model)
        if outline_path:
            outline_path.parent.mkdir(parents=True, exist_ok=True)
            outline_path.write_text(
                json.dumps(outline, indent=2), encoding="utf-8"
            )
            return  # caller will re-invoke after user edits

    # Pass 2: render each slide
    slides_html: list[str] = []
    for slide in outline.get("slides", []):
        try:
            html = _render_slide(slide, artifacts_map, model)
        except Exception as exc:
            html = (
                f"<section><h2>{slide.get('heading', 'Slide')}</h2>"
                f"<p style='color:#f48fb1'>Render error: {exc}</p></section>"
            )
        slides_html.append(html)

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


_OLLAMA_BASE = "http://localhost:11434"


def _chat(model: str, system: str, user: str) -> str:
    """Call LLM via Anthropic SDK routed through Ollama's compatible API.

    Sarathi always uses Ollama as the backend. If ANTHROPIC_BASE_URL is not
    already set (e.g. by `ollama launch claude`), we set it automatically so
    the Anthropic SDK talks to the local Ollama server at port 11434.
    """
    import anthropic

    # Auto-configure Ollama's Anthropic-compatible API if not already set
    if not os.environ.get("ANTHROPIC_BASE_URL"):
        os.environ["ANTHROPIC_BASE_URL"] = _OLLAMA_BASE
    if not os.environ.get("ANTHROPIC_AUTH_TOKEN") and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "ollama"

    base_url = os.environ["ANTHROPIC_BASE_URL"]
    api_key  = os.environ.get("ANTHROPIC_AUTH_TOKEN",
                os.environ.get("ANTHROPIC_API_KEY", "ollama"))

    client = anthropic.Anthropic(base_url=base_url, api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


def _generate_outline(
    project_name: str,
    description: str,
    domain: str,
    files: list[ResultFile],
    model: str,
) -> dict:
    user_msg = _planner_user(project_name, description, domain, files)
    text = _chat(model, _PLANNER_SYSTEM, user_msg)
    return _extract_json(text)


def _render_slide(
    slide: dict,
    artifacts_map: dict[str, ResultFile],
    model: str,
) -> str:
    user_msg = _coder_user(slide, artifacts_map)
    text = _chat(model, _CODER_SYSTEM, user_msg)
    return _extract_section(text)
