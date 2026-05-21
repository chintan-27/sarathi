"""Generate a standalone HTML showcase of all sarathi slide themes."""
from __future__ import annotations
import re
from pathlib import Path

from .builder import _THEME_SKELETONS, _SHARED_CLASSES, _ALL_FONTS_URL

_LEGACY = {"dark-editorial", "light-clean", "bold-gradient", "minimal-mono"}

_DEFAULTS: dict[str, dict] = {
    "editorial-press":    {"accent": "#b8331f", "fh": "DM Serif Display",  "fb": "IBM Plex Sans"},
    "gradient-dreamscape":{"accent": "#d946ef", "fh": "Instrument Serif",  "fb": "Space Grotesk"},
    "blueprint":          {"accent": "#ffb84d", "fh": "Barlow Condensed",  "fb": "IBM Plex Mono"},
    "swiss-brutalism":    {"accent": "#ff3d2e", "fh": "Archivo Black",     "fb": "Space Grotesk"},
    "harvest":            {"accent": "#ea580c", "fh": "Barlow Condensed",  "fb": "IBM Plex Sans"},
    "neon-noir":          {"accent": "#1d4ed8", "fh": "Space Grotesk",     "fb": "Space Grotesk"},
    "broadsheet":         {"accent": "#f97316", "fh": "Archivo Black",     "fb": "IBM Plex Sans"},
    "obsidian":           {"accent": "#84cc16", "fh": "Space Grotesk",     "fb": "Space Grotesk"},
    "kodachrome":         {"accent": "#c2532a", "fh": "DM Serif Display",  "fb": "IBM Plex Sans"},
}

_LABELS = {
    "editorial-press":    "Editorial Press",
    "gradient-dreamscape":"Gradient Dreamscape",
    "blueprint":          "Blueprint",
    "swiss-brutalism":    "Swiss Brutalism",
    "harvest":            "Harvest",
    "neon-noir":          "Neon Noir",
    "broadsheet":         "Broadsheet",
    "obsidian":           "Obsidian",
    "kodachrome":         "Kodachrome",
}

_SWATCHES = {
    "editorial-press":    ["#f4ede2","#1a1614","#b8331f","#4b3e35"],
    "gradient-dreamscape":["#110a26","#d946ef","#06b6d4","#f4ecff"],
    "blueprint":          ["#0c1e2f","#6ea8c9","#ffb84d","#e8f1fa"],
    "swiss-brutalism":    ["#f5f4ef","#0a0a0a","#ff3d2e","#44423e"],
    "harvest":            ["#0d2116","#ea580c","#a8c4a0","#f5f0e8"],
    "neon-noir":          ["#050810","#1d4ed8","#06b6d4","#e8f4ff"],
    "broadsheet":         ["#f7f4ee","#0f0f0f","#f97316","#3d3d3d"],
    "obsidian":           ["#111518","#84cc16","#2a3028","#e8ede8"],
    "kodachrome":         ["#faf5ee","#c2532a","#d4b896","#1c1008"],
}


def _adapt_css(raw: str, cls: str) -> str:
    """Remap Reveal.js selectors to scoped preview selectors."""
    subs = [
        (r"\.reveal-viewport::before", f".{cls}-vp::before"),
        (r"\.reveal-viewport::after",  f".{cls}-vp::after"),
        (r"\.reveal-viewport",         f".{cls}-vp"),
        (r"\.reveal\s+\.slides\s+section::before", f".{cls}-slide::before"),
        (r"\.reveal\s+\.slides\s+section::after",  f".{cls}-slide::after"),
        (r"\.reveal\s+\.slides\s+section",          f".{cls}-slide"),
        (r"\.reveal\s+h1",     f".{cls}-slide h1"),
        (r"\.reveal\s+h2",     f".{cls}-slide h2"),
        (r"\.reveal\s+ul\s*,\s*\.reveal\s+ol", f".{cls}-slide ul, .{cls}-slide ol"),
        (r"\.reveal\s+ul",     f".{cls}-slide ul"),
        (r"\.reveal\s+ol",     f".{cls}-slide ol"),
        (r"\.reveal\s+li",     f".{cls}-slide li"),
        (r"\.reveal\s+pre\s+code", f".{cls}-slide pre code"),
        (r"\.reveal\s+pre",    f".{cls}-slide pre"),
        (r"\.reveal\s+code",   f".{cls}-slide code"),
        (r"\.reveal\s+table",  f".{cls}-slide table"),
        (r"\.reveal\s+\.",     f".{cls}-slide ."),
        (r"\.reveal\b",        f".{cls}-vp"),
    ]
    css = raw
    for pattern, repl in subs:
        css = re.sub(pattern, repl, css)
    return css


def _filled_css(name: str) -> str:
    d = _DEFAULTS[name]
    raw = _THEME_SKELETONS[name] + _SHARED_CLASSES
    filled = raw.format(accent=d["accent"], font_heading=d["fh"], font_body=d["fb"])
    return _adapt_css(filled, name)


def _slide_title(name: str) -> str:
    d = _DEFAULTS[name]
    return f"""
<div class="{name}-vp" style="position:relative">
  <div class="{name}-slide" style="width:1920px;height:1080px;position:absolute;
      top:0;left:0;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-start;">
    <h1>Sarathi</h1>
    <p class="subtitle">Distributed observability for production ML — Q2 2026.</p>
    <p class="subtitle" style="margin-top:1.5em;font-size:.55em;opacity:.6">May 2026 · Engineering Review</p>
  </div>
</div>"""


def _slide_bullets(name: str) -> str:
    return f"""
<div class="{name}-vp" style="position:relative">
  <div class="{name}-slide" style="width:1920px;height:1080px;position:absolute;
      top:0;left:0;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-start;">
    <h2>Four things shipped this quarter.</h2>
    <ul>
      <li>Trace ingestion migrated to Kafka — 12× throughput, same hardware footprint.</li>
      <li>P99 query latency cut from 840 ms to 47 ms via tiered storage rollout.</li>
      <li>Causal trace explorer shipped to 14 design-partner accounts.</li>
      <li>Infrastructure spend down 38% — savings rerouted to GPU eval cluster.</li>
    </ul>
  </div>
</div>"""


def _slide_metric(name: str) -> str:
    return f"""
<div class="{name}-vp" style="position:relative">
  <div class="{name}-slide" style="width:1920px;height:1080px;position:absolute;
      top:0;left:0;overflow:hidden;display:flex;flex-direction:column;justify-content:center;">
    <p class="metric-label">P99 trace-query latency</p>
    <span class="hero-metric">47ms</span>
    <p class="metric-desc">Down from 840 ms — a 94.4% reduction across 2.1B spans/day with no cache layer.</p>
  </div>
</div>"""


def _slide_divider(name: str) -> str:
    return f"""
<div class="{name}-vp" style="position:relative">
  <div class="{name}-slide" style="width:1920px;height:1080px;position:absolute;
      top:0;left:0;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-start;">
    <div class="section-divider">
      <span class="sec-num">03</span>
      <p class="sec-label">Section 03</p>
      <h2 class="sec-title">Architecture</h2>
      <p class="subtitle">Where the bytes flow — and the three places we stopped trying to be clever.</p>
    </div>
  </div>
</div>"""


_SCALE = 0.235
_TW = int(1920 * _SCALE)
_TH = int(1080 * _SCALE)

_SLIDE_LABELS = ["Title", "Bullets", "Metric", "Divider"]


def generate_showcase(output_path: Path) -> None:
    themes = [n for n in _THEME_SKELETONS if n not in _LEGACY]

    all_css = "\n".join(_filled_css(n) for n in themes)

    theme_sections = []
    for name in themes:
        d = _DEFAULTS[name]
        label = _LABELS[name]
        swatches_html = "".join(
            f'<div style="width:22px;height:38px;background:{c};border:1px solid rgba(0,0,0,.1)"></div>'
            for c in _SWATCHES[name]
        )
        slides_html = [
            _slide_title(name), _slide_bullets(name),
            _slide_metric(name), _slide_divider(name),
        ]
        thumbs = ""
        for i, slide_html in enumerate(slides_html):
            thumbs += f"""
        <div>
          <div style="width:{_TW}px;height:{_TH}px;position:relative;overflow:hidden;
              box-shadow:0 1px 0 rgba(0,0,0,.06),0 24px 40px -22px rgba(0,0,0,.22);">
            <div style="transform:scale({_SCALE});transform-origin:top left;
                position:absolute;top:0;left:0;">
              {slide_html}
            </div>
          </div>
          <div style="margin-top:8px;font-family:'JetBrains Mono',monospace;font-size:10px;
              letter-spacing:.16em;text-transform:uppercase;color:#6b6660">
            {_SLIDE_LABELS[i]}
          </div>
        </div>"""

        theme_sections.append(f"""
  <section style="max-width:1760px;margin:0 auto 72px">
    <div style="display:grid;grid-template-columns:64px 1fr auto auto;gap:28px;
        align-items:end;padding-bottom:18px;margin-bottom:22px;
        border-bottom:1px solid #1a1815">
      <div style="font-family:'DM Serif Display',serif;font-size:56px;line-height:.9;
          letter-spacing:-.03em;color:#14120f">{list(themes).index(name)+1:02d}</div>
      <div>
        <div style="font-family:'DM Serif Display',serif;font-size:32px;line-height:1;
            letter-spacing:-.01em;margin:0 0 6px;color:#14120f">{label}</div>
        <div style="font-family:'IBM Plex Sans',sans-serif;font-size:14px;color:#6b6660;
            line-height:1.5">{d["fh"]} · {d["fb"]} · <span style="color:{d["accent"]}">{d["accent"]}</span></div>
      </div>
      <div style="display:flex;gap:5px">{swatches_html}</div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,{_TW}px);gap:20px">
      {thumbs}
    </div>
  </section>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sarathi · Theme Showcase</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{_ALL_FONTS_URL}" rel="stylesheet">
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: #f2efe9; color: #14120f;
  font-family: 'IBM Plex Sans', system-ui, sans-serif; }}
body {{ padding: 64px 56px 120px; }}

{all_css}
</style>
</head>
<body>

<header style="max-width:1760px;margin:0 auto 56px;display:grid;
    grid-template-columns:1.4fr 1fr;gap:64px;align-items:end;
    border-bottom:1px solid #1a1815;padding-bottom:32px">
  <div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;
        text-transform:uppercase;color:#6b6660;margin-bottom:20px">
      Sarathi · slide-theme showcase · {len(themes)} themes
    </div>
    <h1 style="font-family:'DM Serif Display',serif;font-size:72px;font-weight:400;
        line-height:.95;margin:0;letter-spacing:-.02em">
      Nine directions for the <em style="color:#b8331f">Sarathi</em> deck.
    </h1>
  </div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.7;color:#6b6660">
    Same content, nine voices.<br>
    Pick a theme — or mix elements.<br><br>
    <b style="color:#14120f">Project:</b> Sarathi — ML observability<br>
    <b style="color:#14120f">Slides shown:</b> title · bullets · metric · divider
  </div>
</header>

{"".join(theme_sections)}

</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
