from __future__ import annotations

import json
from pathlib import Path

_REGISTRY = Path.home() / ".config" / "sarathi" / "projects.json"


def register_project(project_dir: Path) -> None:
    """Add a project to the global registry."""
    _REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    projects = _load_registry()
    key = str(project_dir.resolve())
    if key not in projects:
        try:
            meta = json.loads((project_dir / "project.json").read_text())
        except Exception:
            meta = {"name": project_dir.name, "description": ""}
        projects[key] = {"path": key, "name": meta.get("name", project_dir.name)}
        _save_registry(projects)


def _load_registry() -> dict:
    if _REGISTRY.exists():
        try:
            return json.loads(_REGISTRY.read_text())
        except Exception:
            pass
    return {}


def _save_registry(data: dict) -> None:
    _REGISTRY.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _project_summary(project_dir: Path) -> dict:
    from . import tracker as trk

    path = project_dir
    meta_path = path / "project.json"
    if not meta_path.exists():
        return {}

    meta = json.loads(meta_path.read_text())
    milestones = trk.get_milestones(path)
    last_gen = trk.last_generated(path)
    pending = trk.files_since_last_generated(path)
    html_exists = (path / "output" / "presentation.html").exists()
    pdf_exists = (path / "output" / "presentation.pdf").exists()
    pptx_exists = any((path / "output").glob("*.pptx")) if (path / "output").exists() else False

    return {
        "name": meta.get("name", path.name),
        "description": meta.get("description", ""),
        "path": str(path),
        "model": meta.get("model", "—"),
        "created": meta.get("created", ""),
        "last_generated": last_gen or "never",
        "milestones": [m.get("label", "") for m in milestones],
        "pending_files": pending,
        "has_html": html_exists,
        "has_pdf": pdf_exists,
        "has_pptx": pptx_exists,
        "html_path": str(path / "output" / "presentation.html") if html_exists else None,
    }


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sarathi Portfolio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

:root {{
  --bg:        #07071a;
  --surface:   #0e0e28;
  --surface2:  #14143a;
  --border:    #1e1e4a;
  --border2:   #2a2a60;
  --accent:    #4fc3f7;
  --accent2:   #7c6fec;
  --green:     #4ade80;
  --yellow:    #fbbf24;
  --red:       #f87171;
  --fg:        #e2e2f2;
  --fg2:       #a0a0c0;
  --fg3:       #606080;
  --glow:      0 0 24px #4fc3f722;
}}

body {{
  background: var(--bg);
  background-image:
    radial-gradient(ellipse 80% 50% at 20% -10%, #1a1060 0%, transparent 60%),
    radial-gradient(ellipse 60% 40% at 80% 110%, #0a2040 0%, transparent 60%);
  color: var(--fg);
  font-family: 'Inter', sans-serif;
  min-height: 100vh;
}}

/* ── Header ── */
header {{
  position: sticky; top: 0; z-index: 100;
  background: rgba(7,7,26,.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  padding: 0 40px;
  display: flex; align-items: center; justify-content: space-between;
  height: 64px;
}}
.logo {{
  display: flex; align-items: center; gap: 12px;
}}
.logo-icon {{
  width: 32px; height: 32px; border-radius: 8px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; font-weight: 700; color: #07071a;
}}
.logo h1 {{ font-size: 1.1rem; font-weight: 700; color: var(--fg); }}
.logo span {{ font-size: .8rem; color: var(--fg3); margin-left: 6px; }}
.header-stats {{ display: flex; gap: 24px; }}
.stat {{ text-align: center; }}
.stat-val {{ font-size: 1.1rem; font-weight: 700; color: var(--accent); line-height: 1; }}
.stat-lbl {{ font-size: .7rem; color: var(--fg3); margin-top: 2px; }}

/* ── Search bar ── */
.toolbar {{
  padding: 24px 40px 0;
  display: flex; gap: 12px; align-items: center;
}}
.search {{
  flex: 1; max-width: 400px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px 14px 9px 36px;
  color: var(--fg); font-size: .875rem; font-family: inherit;
  outline: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23606080' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.35-4.35'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: 12px center;
  transition: border-color .2s;
}}
.search:focus {{ border-color: var(--accent); }}
.search::placeholder {{ color: var(--fg3); }}

/* ── Grid ── */
.grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 20px;
  padding: 24px 40px 60px;
}}

/* ── Card ── */
.card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 0;
  overflow: hidden;
  transition: border-color .25s, box-shadow .25s, transform .2s;
  cursor: default;
  display: flex; flex-direction: column;
}}
.card:hover {{
  border-color: var(--border2);
  box-shadow: var(--glow), 0 8px 32px #0006;
  transform: translateY(-2px);
}}
.card-top {{
  padding: 20px 22px 16px;
  border-bottom: 1px solid var(--border);
  flex: 1;
}}
.card-domain-bar {{
  height: 3px;
  border-radius: 0 0 0 0;
  margin: -1px -1px 16px;
  width: calc(100% + 2px);
}}
.domain-ml    {{ background: linear-gradient(90deg, #7c6fec, #4fc3f7); }}
.domain-software {{ background: linear-gradient(90deg, #4ade80, #22d3ee); }}
.domain-data  {{ background: linear-gradient(90deg, #fbbf24, #f87171); }}
.domain-diff  {{ background: linear-gradient(90deg, #a78bfa, #ec4899); }}
.domain-auto  {{ background: linear-gradient(90deg, #4fc3f7, #7c6fec); }}
.card-header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }}
.card h2 {{ font-size: 1rem; font-weight: 600; color: var(--fg); line-height: 1.3; }}
.domain-pill {{
  font-size: .65rem; font-weight: 600; padding: 2px 8px; border-radius: 20px;
  text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; flex-shrink: 0;
}}
.pill-ml    {{ background: #1a1060; color: #a78bfa; border: 1px solid #3a2888; }}
.pill-software {{ background: #0a2a1a; color: #4ade80; border: 1px solid #1a5030; }}
.pill-data  {{ background: #2a1a00; color: #fbbf24; border: 1px solid #5a3800; }}
.pill-auto  {{ background: #0a1a2a; color: var(--accent); border: 1px solid #1a3a5a; }}
.card-desc {{ color: var(--fg3); font-size: .8rem; margin-top: 6px; line-height: 1.5; min-height: 2.4em; }}
.card-meta {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 10px; margin-top: 14px;
}}
.meta-item {{ display: flex; flex-direction: column; gap: 2px; }}
.meta-label {{ font-size: .65rem; color: var(--fg3); text-transform: uppercase; letter-spacing: .06em; }}
.meta-val   {{ font-size: .8rem; color: var(--fg2); font-weight: 500; }}
.meta-val.accent {{ color: var(--accent); }}

/* Milestones */
.milestones {{ margin-top: 14px; }}
.milestones-label {{ font-size: .65rem; color: var(--fg3); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }}
.milestone-list {{ display: flex; flex-wrap: wrap; gap: 5px; }}
.mtag {{
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--surface2); border: 1px solid var(--border2);
  color: var(--fg2); border-radius: 5px; font-size: .72rem;
  padding: 2px 8px;
}}
.mtag::before {{ content: "★"; color: var(--yellow); font-size: .65rem; }}

/* Pending warning */
.pending {{
  margin-top: 12px; padding: 8px 12px;
  background: #2a1500; border: 1px solid #5a3000;
  border-radius: 8px; font-size: .75rem; color: var(--yellow);
  display: flex; align-items: center; gap: 6px;
}}

/* Card bottom */
.card-bottom {{
  padding: 14px 22px;
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
}}
.output-badges {{ display: flex; gap: 6px; }}
.obadge {{
  font-size: .7rem; font-weight: 600; padding: 3px 9px; border-radius: 5px;
}}
.ob-html {{ background: #0a3020; color: #4ade80; border: 1px solid #1a5030; }}
.ob-pdf  {{ background: #0a2040; color: var(--accent); border: 1px solid #1a4060; }}
.ob-pptx {{ background: #1a1a00; color: #fbbf24; border: 1px solid #3a3a00; }}
.ob-none {{ background: #2a0a0a; color: var(--red); border: 1px solid #5a1a1a; font-style: italic; }}
.card-actions {{ display: flex; gap: 6px; }}
.btn {{
  padding: 6px 14px; border-radius: 7px; font-size: .78rem; font-weight: 600;
  text-decoration: none; border: none; cursor: pointer;
  transition: opacity .15s, transform .1s;
  display: inline-flex; align-items: center; gap: 5px;
}}
.btn:hover {{ opacity: .85; transform: translateY(-1px); }}
.btn-primary {{ background: var(--accent); color: #07071a; }}
.btn-ghost   {{ background: transparent; color: var(--fg2); border: 1px solid var(--border2); }}

/* Empty state */
.empty {{
  grid-column: 1/-1; text-align: center; padding: 100px 40px; color: var(--fg3);
}}
.empty-icon {{ font-size: 3rem; margin-bottom: 16px; }}
.empty h2 {{ color: var(--fg2); margin-bottom: 8px; }}
.empty code {{
  background: var(--surface); border: 1px solid var(--border);
  padding: 2px 8px; border-radius: 5px; font-size: .875rem; color: var(--accent);
}}

/* Refresh FAB */
.fab {{
  position: fixed; bottom: 24px; right: 24px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  color: #07071a; border: none; border-radius: 50%;
  width: 48px; height: 48px; font-size: 1.2rem;
  cursor: pointer; box-shadow: 0 4px 20px #4fc3f744;
  transition: transform .2s, box-shadow .2s;
  display: flex; align-items: center; justify-content: center;
}}
.fab:hover {{ transform: scale(1.1) rotate(15deg); box-shadow: 0 6px 28px #4fc3f766; }}

/* Search filter */
.card.hidden {{ display: none; }}
</style>
</head>
<body>
<header>
  <div class="logo">
    <div class="logo-icon">S</div>
    <h1>Sarathi</h1>
    <span>portfolio</span>
  </div>
  <div class="header-stats">
    <div class="stat"><div class="stat-val" id="s-projects">—</div><div class="stat-lbl">Projects</div></div>
    <div class="stat"><div class="stat-val" id="s-milestones">—</div><div class="stat-lbl">Milestones</div></div>
    <div class="stat"><div class="stat-val" id="s-generated">—</div><div class="stat-lbl">Generated</div></div>
  </div>
</header>
<div class="toolbar">
  <input class="search" id="search" type="text" placeholder="Search projects…" oninput="filterCards(this.value)">
</div>
<div class="grid" id="grid">
CARDS_PLACEHOLDER
</div>
<button class="fab" onclick="location.reload()" title="Refresh">↻</button>
<script>
const cards = Array.from(document.querySelectorAll('.card'));
document.getElementById('s-projects').textContent = cards.length;
const ml = cards.reduce((n,c) => n + (c.querySelectorAll('.mtag').length), 0);
document.getElementById('s-milestones').textContent = ml;
const gen = cards.filter(c => c.querySelector('.ob-html,.ob-pdf,.ob-pptx')).length;
document.getElementById('s-generated').textContent = gen;
function filterCards(q) {{
  q = q.toLowerCase();
  cards.forEach(c => {{
    const text = c.textContent.toLowerCase();
    c.classList.toggle('hidden', q.length > 0 && !text.includes(q));
  }});
}}
</script>
</body>
</html>
"""


def _domain_pill(domain: str) -> str:
    mapping = {
        "ml":       ("pill-ml",       "ML"),
        "software": ("pill-software", "Software"),
        "data":     ("pill-data",     "Data"),
        "diff":     ("pill-auto",     "Diff"),
    }
    cls, label = mapping.get(domain, ("pill-auto", domain.title()))
    return f'<span class="domain-pill {cls}">{label}</span>'


def _card_html(summary: dict) -> str:
    name      = summary.get("name", "Unnamed")
    desc      = summary.get("description", "") or ""
    model     = summary.get("model", "—")
    created   = (summary.get("created") or "")[:10]
    last_gen  = summary.get("last_generated", "never")
    milestones = summary.get("milestones", [])
    pending   = summary.get("pending_files", [])
    has_html  = summary.get("has_html", False)
    has_pdf   = summary.get("has_pdf", False)
    has_pptx  = summary.get("has_pptx", False)
    html_path = summary.get("html_path", "")
    path      = summary.get("path", "")
    domain    = "auto"

    # Output badges
    output_badges = []
    if has_html:
        output_badges.append('<span class="obadge ob-html">HTML</span>')
    if has_pdf:
        output_badges.append('<span class="obadge ob-pdf">PDF</span>')
    if has_pptx:
        output_badges.append('<span class="obadge ob-pptx">PPTX</span>')
    if not (has_html or has_pdf or has_pptx):
        output_badges.append('<span class="obadge ob-none">No output</span>')

    # Milestone tags (last 4)
    milestone_html = ""
    if milestones:
        tags = "".join(f'<span class="mtag">{m}</span>' for m in milestones[-4:])
        milestone_html = f'''
  <div class="milestones">
    <div class="milestones-label">Milestones ({len(milestones)})</div>
    <div class="milestone-list">{tags}</div>
  </div>'''

    # Pending files warning
    pending_html = ""
    if pending:
        pending_html = (
            f'<div class="pending">⚠ {len(pending)} file(s) changed since last run</div>'
        )

    # Action buttons
    open_btn = (
        f'<a class="btn btn-primary" href="/open?path={html_path}" target="_blank">▶ Open</a>'
        if has_html else ""
    )
    status_btn = f'<a class="btn btn-ghost" href="/status?path={path}">JSON</a>'

    return f"""
<div class="card">
  <div class="domain-bar card-domain-bar domain-{domain}"></div>
  <div class="card-top">
    <div class="card-header">
      <h2>{name}</h2>
      {_domain_pill(domain)}
    </div>
    <div class="card-desc">{desc[:120] + ('…' if len(desc) > 120 else '')}</div>
    <div class="card-meta">
      <div class="meta-item">
        <span class="meta-label">Model</span>
        <span class="meta-val accent">{model}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Created</span>
        <span class="meta-val">{created or '—'}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Last generated</span>
        <span class="meta-val">{last_gen}</span>
      </div>
      <div class="meta-item">
        <span class="meta-label">Milestones</span>
        <span class="meta-val">{len(milestones)}</span>
      </div>
    </div>
    {milestone_html}
    {pending_html}
  </div>
  <div class="card-bottom">
    <div class="output-badges">{''.join(output_badges)}</div>
    <div class="card-actions">
      {open_btn}
      {status_btn}
    </div>
  </div>
</div>"""


def serve(port: int = 7432, extra_dirs: list[str] | None = None) -> None:
    """Start the portfolio web server."""
    from flask import Flask, request, redirect, Response
    import webbrowser, threading

    app = Flask(__name__)

    @app.route("/")
    def index():
        projects: dict[str, dict] = {}

        registry = _load_registry()
        for key, info in registry.items():
            p = Path(info["path"])
            if p.exists():
                s = _project_summary(p)
                if s:
                    projects[key] = s

        if extra_dirs:
            for d in extra_dirs:
                p = Path(d).resolve()
                if p.exists() and (p / "project.json").exists():
                    s = _project_summary(p)
                    if s:
                        projects[str(p)] = s

        if not projects:
            cards = '<div class="empty"><h2>No projects found</h2><p>Run <code>sarathi arambh</code> to create one.</p></div>'
        else:
            cards = "".join(_card_html(s) for s in projects.values())

        html = _HTML_TEMPLATE.replace("CARDS_PLACEHOLDER", cards)
        return Response(html, content_type="text/html")

    @app.route("/open")
    def open_file():
        path = request.args.get("path", "")
        if path and Path(path).exists():
            return redirect(f"file://{path}")
        return "Not found", 404

    @app.route("/status")
    def status_page():
        path = request.args.get("path", "")
        p = Path(path)
        if not p.exists():
            return "Not found", 404
        s = _project_summary(p)
        return Response(
            f"<pre style='background:#111;color:#eee;padding:20px'>"
            f"{json.dumps(s, indent=2)}</pre>",
            content_type="text/html",
        )

    url = f"http://localhost:{port}"
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"\n  Sarathi Portfolio →  {url}\n  Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
