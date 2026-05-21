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
    """
    1. Scope :root CSS custom properties to the theme container so themes
       don't bleed into each other on the same page.
    2. Remap all Reveal.js selectors to scoped preview selectors.
    """
    css = raw

    # ── Step 1: scope :root to the theme container ───────────────────────────
    css = re.sub(r':root\s*\{', f'.{cls}-vp, .{cls}-slide {{', css)

    # ── Step 2: remap Reveal.js selectors (longest/most-specific first) ──────
    subs = [
        (r"\.reveal-viewport::before",                  f".{cls}-vp::before"),
        (r"\.reveal-viewport::after",                   f".{cls}-vp::after"),
        (r"\.reveal-viewport",                          f".{cls}-vp"),
        (r"\.reveal\s+\.slides\s+section::before",      f".{cls}-slide::before"),
        (r"\.reveal\s+\.slides\s+section::after",       f".{cls}-slide::after"),
        (r"\.reveal\s+\.slides\s+section",              f".{cls}-slide"),
        (r"\.reveal\s+h1",                              f".{cls}-slide h1"),
        (r"\.reveal\s+h2",                              f".{cls}-slide h2"),
        (r"\.reveal\s+ul\s*,\s*\.reveal\s+ol",         f".{cls}-slide ul, .{cls}-slide ol"),
        (r"\.reveal\s+ul",                              f".{cls}-slide ul"),
        (r"\.reveal\s+ol",                              f".{cls}-slide ol"),
        (r"\.reveal\s+li",                              f".{cls}-slide li"),
        (r"\.reveal\s+pre\s+code",                      f".{cls}-slide pre code"),
        (r"\.reveal\s+pre",                             f".{cls}-slide pre"),
        (r"\.reveal\s+code",                            f".{cls}-slide code"),
        (r"\.reveal\s+table",                           f".{cls}-slide table"),
        (r"\.reveal\s+\.",                              f".{cls}-slide ."),
        (r"\.reveal\b",                                 f".{cls}-vp"),
    ]
    for pattern, repl in subs:
        css = re.sub(pattern, repl, css)

    return css


def _filled_css(name: str) -> str:
    d = _DEFAULTS[name]
    raw = _THEME_SKELETONS[name] + _SHARED_CLASSES
    filled = raw.format(accent=d["accent"], font_heading=d["fh"], font_body=d["fb"])
    return _adapt_css(filled, name)


# ── Sample slide content (same across all themes for direct comparison) ───────

def _slide(name: str, inner: str) -> str:
    return (
        f'<div class="{name}-vp" style="width:1920px;height:1080px;overflow:hidden">'
        f'<div class="{name}-slide">{inner}</div>'
        f'</div>'
    )


def _slide_title(name: str) -> str:
    return _slide(name, """
      <div style="padding:80px 96px;display:flex;flex-direction:column;justify-content:center;height:100%">
        <h1 style="font-size:280px;margin-bottom:40px">Sarathi</h1>
        <p class="subtitle" style="font-size:48px">Distributed observability for production ML — Q2 2026.</p>
        <p class="subtitle" style="margin-top:60px;font-size:28px;opacity:.55">May 2026 · Engineering Review · 21 slides</p>
      </div>
    """)


def _slide_bullets(name: str) -> str:
    return _slide(name, """
      <div style="padding:80px 96px;display:flex;flex-direction:column;height:100%">
        <h2 style="font-size:96px;margin-bottom:48px">Four things shipped this quarter.</h2>
        <ul style="font-size:36px">
          <li style="font-size:36px">Trace ingestion migrated to Kafka — 12× throughput, same hardware.</li>
          <li style="font-size:36px">P99 query latency cut from 840 ms to 47 ms via tiered storage.</li>
          <li style="font-size:36px">Causal trace explorer shipped to 14 design-partner accounts.</li>
          <li style="font-size:36px">Infrastructure spend down 38% — rerouted to GPU eval cluster.</li>
        </ul>
      </div>
    """)


def _slide_metric(name: str) -> str:
    return _slide(name, """
      <div style="display:flex;flex-direction:column;justify-content:center;flex:1;height:100%;padding:80px 96px">
        <p class="metric-label" style="font-size:26px;margin-bottom:16px">P99 trace-query latency</p>
        <span class="hero-metric" style="font-size:460px">47ms</span>
        <p class="metric-desc" style="font-size:32px;margin-top:24px">Down from 840 ms — a 94.4% reduction across 2.1B spans/day with no cache layer.</p>
      </div>
    """)


def _slide_divider(name: str) -> str:
    return _slide(name, """
      <div class="section-divider" style="height:100%;padding:80px 96px">
        <span class="sec-num" style="font-size:360px">03</span>
        <p class="sec-label" style="font-size:26px;margin-top:16px">Section 03 of 05</p>
        <h2 class="sec-title" style="font-size:120px;margin-top:8px">Architecture</h2>
        <p class="subtitle" style="font-size:32px;margin-top:16px">Where the bytes flow — and the three places we stopped trying to be clever.</p>
      </div>
    """)


_SCALE = 0.235
_TW = int(1920 * _SCALE)
_TH = int(1080 * _SCALE)
_SLIDE_LABELS = ["Title", "Bullets", "Metric", "Divider"]


def generate_showcase(output_path: Path) -> None:
    themes = [n for n in _THEME_SKELETONS if n not in _LEGACY]

    all_css = "\n".join(_filled_css(n) for n in themes)

    # Force each theme's slide to fill its 1920×1080 box
    base_css = "\n".join(
        f".{n}-slide {{ "
        f"width:1920px !important; height:1080px !important; "
        f"box-sizing:border-box !important; overflow:hidden !important; }}"
        for n in themes
    )

    theme_sections = []
    for idx, name in enumerate(themes):
        d = _DEFAULTS[name]
        label = _LABELS[name]
        swatches_html = "".join(
            f'<div style="width:22px;height:38px;background:{c};'
            f'border:1px solid rgba(0,0,0,.1);flex-shrink:0"></div>'
            for c in _SWATCHES[name]
        )
        slides = [_slide_title(name), _slide_bullets(name),
                  _slide_metric(name), _slide_divider(name)]
        thumbs = ""
        for i, slide_html in enumerate(slides):
            thumbs += f"""
        <div>
          <div style="width:{_TW}px;height:{_TH}px;overflow:hidden;position:relative;
              box-shadow:0 2px 0 rgba(0,0,0,.06),0 20px 40px -18px rgba(0,0,0,.28);">
            <div style="transform:scale({_SCALE});transform-origin:top left;
                width:1920px;height:1080px;position:absolute;top:0;left:0;">
              {slide_html}
            </div>
          </div>
          <div style="margin-top:8px;font-family:'JetBrains Mono',monospace;font-size:10px;
              letter-spacing:.16em;text-transform:uppercase;color:#6b6660">{_SLIDE_LABELS[i]}</div>
        </div>"""

        theme_sections.append(f"""
  <section style="max-width:1760px;margin:0 auto 72px">
    <div style="display:grid;grid-template-columns:56px 1fr auto auto;gap:28px;
        align-items:end;padding-bottom:18px;margin-bottom:24px;
        border-bottom:1px solid #1a1815">
      <div style="font-family:'DM Serif Display',serif;font-size:52px;line-height:.9;
          letter-spacing:-.03em;color:#14120f">{idx+1:02d}</div>
      <div>
        <div style="font-family:'DM Serif Display',serif;font-size:30px;line-height:1;
            letter-spacing:-.01em;margin:0 0 5px;color:#14120f">{label}</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:11px;
            line-height:1.6;color:#6b6660">
          {d["fh"]} · {d["fb"]} · <span style="color:{d["accent"]};font-weight:600">{d["accent"]}</span>
        </div>
      </div>
      <div style="display:flex;gap:5px;align-items:flex-end">{swatches_html}</div>
    </div>
    <div style="display:flex;gap:20px;flex-wrap:nowrap">
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
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: #f2efe9; color: #14120f;
  font-family: 'IBM Plex Sans', system-ui, sans-serif; }}
body {{ padding: 64px 56px 120px; }}

{base_css}

{all_css}
</style>
</head>
<body>

<header style="max-width:1760px;margin:0 auto 60px;display:grid;
    grid-template-columns:1.4fr 1fr;gap:64px;align-items:end;
    border-bottom:1px solid #1a1815;padding-bottom:32px">
  <div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;
        text-transform:uppercase;color:#6b6660;margin-bottom:18px">
      Sarathi · slide-theme showcase · {len(themes)} themes
    </div>
    <h1 style="font-family:'DM Serif Display',serif;font-size:68px;font-weight:400;
        line-height:.95;letter-spacing:-.02em">
      Nine directions for the<br><em style="color:#b8331f">Sarathi</em> deck.
    </h1>
  </div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.8;color:#6b6660">
    Same content, nine voices.<br>
    Pick a theme or mix elements.<br><br>
    <span style="color:#14120f">Project:</span> Sarathi — ML observability<br>
    <span style="color:#14120f">Slides:</span> title · bullets · metric · divider
  </div>
</header>

{"".join(theme_sections)}

</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
