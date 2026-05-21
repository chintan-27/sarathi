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
    css = raw
    # Scope :root CSS variables to the theme container so themes don't bleed into each other
    css = re.sub(r':root\s*\{', f'.{cls}-vp, .{cls}-slide {{', css)
    # Remap Reveal.js selectors (longest/most-specific first)
    subs = [
        (r"\.reveal-viewport::before",             f".{cls}-vp::before"),
        (r"\.reveal-viewport::after",              f".{cls}-vp::after"),
        (r"\.reveal-viewport",                     f".{cls}-vp"),
        (r"\.reveal\s+\.slides\s+section::before", f".{cls}-slide::before"),
        (r"\.reveal\s+\.slides\s+section::after",  f".{cls}-slide::after"),
        (r"\.reveal\s+\.slides\s+section",         f".{cls}-slide"),
        (r"\.reveal\s+h1",                         f".{cls}-slide h1"),
        (r"\.reveal\s+h2",                         f".{cls}-slide h2"),
        (r"\.reveal\s+ul\s*,\s*\.reveal\s+ol",    f".{cls}-slide ul, .{cls}-slide ol"),
        (r"\.reveal\s+ul",                         f".{cls}-slide ul"),
        (r"\.reveal\s+ol",                         f".{cls}-slide ol"),
        (r"\.reveal\s+li",                         f".{cls}-slide li"),
        (r"\.reveal\s+pre\s+code",                 f".{cls}-slide pre code"),
        (r"\.reveal\s+pre",                        f".{cls}-slide pre"),
        (r"\.reveal\s+code",                       f".{cls}-slide code"),
        (r"\.reveal\s+table",                      f".{cls}-slide table"),
        (r"\.reveal\s+\.",                         f".{cls}-slide ."),
        (r"\.reveal\b",                            f".{cls}-vp"),
    ]
    for pattern, repl in subs:
        css = re.sub(pattern, repl, css)
    return css


def _filled_css(name: str) -> str:
    d = _DEFAULTS[name]
    raw = _THEME_SKELETONS[name] + _SHARED_CLASSES
    filled = raw.format(accent=d["accent"], font_heading=d["fh"], font_body=d["fb"])
    return _adapt_css(filled, name)


# ── Slide builders ─────────────────────────────────────────────────────────────
# font-size: 42px on the slide matches Reveal.js's default base,
# so em/rem values in theme CSS produce correct proportions inside the 1920px container.

def _slide(name: str, inner: str) -> str:
    return (
        f'<div class="{name}-vp" style="width:1920px;height:1080px;overflow:hidden">'
        f'<div class="{name}-slide" style="font-size:42px">{inner}</div>'
        f'</div>'
    )


def _slide_title(name: str) -> str:
    return _slide(name, """
      <h1>Sarathi</h1>
      <p class="subtitle">Distributed observability for production ML — Q2 2026.</p>
      <p class="subtitle" style="margin-top:1.5em;opacity:.5">May 2026 · Engineering Review</p>
    """)


def _slide_bullets(name: str) -> str:
    return _slide(name, """
      <h2>Four things shipped this quarter.</h2>
      <ul>
        <li>Trace ingestion on Kafka — 12× throughput, same hardware footprint.</li>
        <li>P99 latency cut from 840 ms to 47 ms via tiered storage.</li>
        <li>Causal trace explorer live at 14 design-partner accounts.</li>
        <li>Infrastructure spend down 38% — rerouted to GPU eval cluster.</li>
      </ul>
    """)


def _slide_grid(name: str) -> str:
    return _slide(name, """
      <h2>How Sarathi Works</h2>
      <div class="slide-grid">
        <div class="grid-card"><h4>Trace Ingestion</h4><p>Kafka-backed pipeline at 12× throughput with automatic back-pressure.</p></div>
        <div class="grid-card"><h4>Tiered Storage</h4><p>Hot/warm/cold tiers reduce query latency from 840 ms to 47 ms.</p></div>
        <div class="grid-card"><h4>Causal Explorer</h4><p>Correlate traces across services without manually writing joins.</p></div>
        <div class="grid-card"><h4>Cost Control</h4><p>38% infra spend reduction with intelligent data lifecycle policies.</p></div>
      </div>
    """)


def _slide_metric(name: str) -> str:
    return _slide(name, """
      <div style="display:flex;flex-direction:column;justify-content:center;height:100%">
        <p class="metric-label">P99 trace-query latency</p>
        <span class="hero-metric">47ms</span>
        <p class="metric-desc">Down from 840 ms — 94.4% reduction across 2.1B spans/day, no cache layer.</p>
      </div>
    """)


def _slide_comparison(name: str) -> str:
    return _slide(name, """
      <h2>Before and After the Migration</h2>
      <div class="slide-split">
        <div>
          <p style="font-size:.62em;text-transform:uppercase;letter-spacing:.15em;opacity:.55;margin-bottom:.5em">Before</p>
          <p style="font-size:.85em;line-height:1.55">Single-threaded ingestion. 840 ms p99. $180K/month. No causal correlation across services.</p>
        </div>
        <div>
          <p style="font-size:.62em;text-transform:uppercase;letter-spacing:.15em;color:var(--accent);margin-bottom:.5em">After</p>
          <p style="font-size:.85em;line-height:1.55">Kafka pipeline. 47 ms p99. $112K/month (−38%). Causal trace explorer in production at 14 accounts.</p>
        </div>
      </div>
    """)


def _slide_statement(name: str) -> str:
    return _slide(name, """
      <div class="statement-slide" style="height:100%">
        <p class="stmt">The model doesn't lie. <em>The observability layer does.</em></p>
        <p class="subtitle" style="margin-top:1.2em;max-width:28ch">Every outage in production ML traces back to a gap in what we could observe — not what the model predicted.</p>
      </div>
    """)


def _slide_table(name: str) -> str:
    d = _DEFAULTS[name]
    return _slide(name, f"""
      <h2>Latency Improvements Across All Percentiles</h2>
      <table style="width:100%;border-collapse:collapse;font-size:.72em;text-align:left;margin-top:.5em">
        <thead>
          <tr style="border-bottom:2px solid {d['accent']}">
            <th style="padding:.4em .8em;font-weight:600">Percentile</th>
            <th style="padding:.4em .8em;font-weight:600">Q1 (Before)</th>
            <th style="padding:.4em .8em;font-weight:600">Q2 (After)</th>
            <th style="padding:.4em .8em;font-weight:600">Delta</th>
            <th style="padding:.4em .8em;font-weight:600">Workload</th>
          </tr>
        </thead>
        <tbody>
          <tr style="border-bottom:1px solid var(--border)">
            <td style="padding:.38em .8em">p50</td><td style="padding:.38em .8em">210 ms</td>
            <td style="padding:.38em .8em;color:{d['accent']}">12 ms</td><td style="padding:.38em .8em">−94.3%</td>
            <td style="padding:.38em .8em">2.1 B spans/day</td>
          </tr>
          <tr style="border-bottom:1px solid var(--border)">
            <td style="padding:.38em .8em">p75</td><td style="padding:.38em .8em">480 ms</td>
            <td style="padding:.38em .8em;color:{d['accent']}">28 ms</td><td style="padding:.38em .8em">−94.2%</td>
            <td style="padding:.38em .8em">2.1 B spans/day</td>
          </tr>
          <tr style="border-bottom:1px solid var(--border)">
            <td style="padding:.38em .8em">p99</td><td style="padding:.38em .8em">840 ms</td>
            <td style="padding:.38em .8em;color:{d['accent']}">47 ms</td><td style="padding:.38em .8em">−94.4%</td>
            <td style="padding:.38em .8em">2.1 B spans/day</td>
          </tr>
          <tr>
            <td style="padding:.38em .8em">p99.9</td><td style="padding:.38em .8em">2,100 ms</td>
            <td style="padding:.38em .8em;color:{d['accent']}">140 ms</td><td style="padding:.38em .8em">−93.3%</td>
            <td style="padding:.38em .8em">2.1 B spans/day</td>
          </tr>
        </tbody>
      </table>
      <p class="subtitle" style="margin-top:.6em">No regressions across any measured percentile after the Kafka migration.</p>
    """)


def _slide_image(name: str) -> str:
    d = _DEFAULTS[name]
    # Simulate a chart with a styled placeholder — gradient bars
    bars = "".join(
        f'<div style="display:flex;align-items:flex-end;gap:0;height:100%">'
        + "".join(
            f'<div style="flex:1;background:{d["accent"]};opacity:{0.3 + i*0.1:.1f};margin:0 4px;'
            f'height:{h}%"></div>'
            for i, h in enumerate([30, 45, 38, 62, 55, 78, 65, 92, 85, 100])
        )
        + "</div>"
    )
    return _slide(name, f"""
      <h2>Throughput Grew 12× After the Kafka Migration</h2>
      <div style="flex:1;display:flex;flex-direction:column;margin-top:.4em">
        <div style="flex:1;border-left:2px solid var(--border);border-bottom:2px solid var(--border);
            padding:1rem;position:relative;min-height:0">
          <div style="position:absolute;inset:.8rem;display:flex;align-items:flex-end;gap:3px">
            {''.join(f'<div style="flex:1;background:{d["accent"]};opacity:{0.25 + i*0.08:.2f};margin:0 3px;height:{h}%"></div>' for i, h in enumerate([22,35,28,48,42,61,54,75,68,100,88,95]))}
          </div>
          <div style="position:absolute;bottom:.2rem;left:.8rem;right:.8rem;
              display:flex;justify-content:space-between;font-size:.4em;opacity:.5">
            <span>Jan</span><span>Feb</span><span>Mar</span><span>Apr</span>
            <span>May</span><span>Jun</span><span>Jul</span><span>Aug</span>
            <span>Sep</span><span>Oct</span><span>Nov</span><span>Dec</span>
          </div>
        </div>
        <p class="subtitle" style="margin-top:.5em">Spans ingested per second · pre-migration baseline = 1×</p>
      </div>
    """)


def _slide_divider(name: str) -> str:
    return _slide(name, """
      <div class="section-divider" style="height:100%">
        <span class="sec-num">03</span>
        <p class="sec-label">Section 03 of 05</p>
        <h2 class="sec-title">Architecture</h2>
        <p class="subtitle">Where the bytes flow — and the three places we stopped trying to be clever.</p>
      </div>
    """)


_SCALE = 0.195
_TW = int(1920 * _SCALE)
_TH = int(1080 * _SCALE)

_SLIDE_FNS = [
    ("Title",      _slide_title),
    ("Bullets",    _slide_bullets),
    ("Grid",       _slide_grid),
    ("Metric",     _slide_metric),
    ("Comparison", _slide_comparison),
    ("Statement",  _slide_statement),
    ("Table",      _slide_table),
    ("Chart",      _slide_image),
    ("Divider",    _slide_divider),
]


def generate_showcase(output_path: Path) -> None:
    themes = [n for n in _THEME_SKELETONS if n not in _LEGACY]

    all_css = "\n".join(_filled_css(n) for n in themes)

    # Ensure slide boxes fill their container
    base_css = "\n".join(
        f".{n}-slide {{ width:1920px !important; height:1080px !important; "
        f"box-sizing:border-box !important; overflow:hidden !important; }}"
        for n in themes
    )

    theme_sections = []
    for idx, name in enumerate(themes):
        d = _DEFAULTS[name]
        label = _LABELS[name]
        swatches_html = "".join(
            f'<div style="width:20px;height:34px;background:{c};'
            f'border:1px solid rgba(0,0,0,.1);flex-shrink:0"></div>'
            for c in _SWATCHES[name]
        )

        thumbs = ""
        for slide_label, fn in _SLIDE_FNS:
            thumbs += f"""
        <div style="flex-shrink:0">
          <div style="width:{_TW}px;height:{_TH}px;overflow:hidden;position:relative;
              box-shadow:0 2px 0 rgba(0,0,0,.07),0 18px 36px -16px rgba(0,0,0,.26);">
            <div style="transform:scale({_SCALE});transform-origin:top left;
                width:1920px;height:1080px;position:absolute;top:0;left:0;">
              {fn(name)}
            </div>
          </div>
          <div style="margin-top:7px;font-family:'JetBrains Mono',monospace;font-size:9.5px;
              letter-spacing:.16em;text-transform:uppercase;color:#6b6660">{slide_label}</div>
        </div>"""

        theme_sections.append(f"""
  <section style="max-width:1840px;margin:0 auto 72px">
    <div style="display:grid;grid-template-columns:52px 1fr auto auto;gap:24px;
        align-items:end;padding-bottom:16px;margin-bottom:20px;
        border-bottom:1px solid #1a1815">
      <div style="font-family:'DM Serif Display',serif;font-size:48px;line-height:.9;
          letter-spacing:-.03em;color:#14120f">{idx+1:02d}</div>
      <div>
        <div style="font-family:'DM Serif Display',serif;font-size:28px;line-height:1;
            letter-spacing:-.01em;margin:0 0 5px;color:#14120f">{label}</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:11px;
            line-height:1.6;color:#6b6660">
          {d["fh"]} · {d["fb"]} · <span style="color:{d['accent']};font-weight:600">{d['accent']}</span>
        </div>
      </div>
      <div style="display:flex;gap:5px;align-items:flex-end">{swatches_html}</div>
    </div>
    <div style="display:flex;gap:16px;flex-wrap:wrap">
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
body {{ padding: 64px 52px 120px; }}
{base_css}
{all_css}
</style>
</head>
<body>

<header style="max-width:1840px;margin:0 auto 60px;display:grid;
    grid-template-columns:1.4fr 1fr;gap:64px;align-items:end;
    border-bottom:1px solid #1a1815;padding-bottom:32px">
  <div>
    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;
        text-transform:uppercase;color:#6b6660;margin-bottom:18px">
      Sarathi · slide-theme showcase · {len(themes)} themes · 7 slide types each
    </div>
    <h1 style="font-family:'DM Serif Display',serif;font-size:64px;font-weight:400;
        line-height:.95;letter-spacing:-.02em">
      Nine directions for the<br><em style="color:#b8331f">Sarathi</em> deck.
    </h1>
  </div>
  <div style="font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.9;color:#6b6660">
    Same content, nine voices.<br>
    <span style="color:#14120f">Slides shown:</span>
    title · bullets · grid · metric · comparison · statement · divider
  </div>
</header>

{"".join(theme_sections)}

</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
