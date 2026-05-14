from __future__ import annotations

import json
from pathlib import Path

_REGISTRY = Path.home() / ".config" / "sarathi" / "projects.json"


def register_project(project_dir: Path) -> None:
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
    import subprocess, re
    from . import tracker as trk
    from . import config as cfg
    from . import scanner as sc

    path = project_dir
    meta_path = path / "project.json"
    if not meta_path.exists():
        return {}

    meta     = json.loads(meta_path.read_text())
    pcfg     = cfg.load_project_config(path)
    timeline = trk.get_timeline(path)
    milestones  = [e for e in timeline if e.get("event") == "milestone"]
    gen_events  = [e for e in timeline if e.get("event") == "generated"]
    last_gen    = gen_events[-1]["ts"] if gen_events else None
    pending     = trk.files_since_last_generated(path)

    html_path   = path / "output" / "presentation.html"
    pdf_path    = path / "output" / "presentation.pdf"
    html_exists = html_path.exists()
    pdf_exists  = pdf_path.exists()
    pptx_files  = list((path / "output").glob("*.pptx")) if (path / "output").exists() else []

    slide_count = 0
    html_size   = ""
    if html_exists:
        try:
            txt = html_path.read_text(encoding="utf-8", errors="replace")
            slide_count = len(re.findall(r"<section", txt, re.IGNORECASE))
            sz = html_path.stat().st_size
            html_size = f"{sz/1024:.0f} KB" if sz < 1_000_000 else f"{sz/1_000_000:.1f} MB"
        except Exception:
            pass

    try:
        files = sc.scan(path)
        ft = {"image": 0, "data": 0, "text": 0, "code": 0, "svg": 0}
        for f in files:
            ft[f.type] = ft.get(f.type, 0) + 1
    except Exception:
        ft = {}

    git_branch = git_commits = git_last_msg = git_last_date = ""
    try:
        def _g(cmd):
            return subprocess.run(cmd, cwd=str(path), capture_output=True,
                                  text=True, timeout=3).stdout.strip()
        git_branch  = _g(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        git_commits = _g(["git", "rev-list", "--count", "HEAD"])
        last_log    = _g(["git", "log", "-1", "--format=%s|%ad", "--date=short"])
        if "|" in last_log:
            git_last_msg, git_last_date = last_log.split("|", 1)
            git_last_msg = git_last_msg[:55]
    except Exception:
        pass

    created_str = meta.get("created", "")
    project_age = ""
    if created_str:
        try:
            from datetime import datetime
            age = (datetime.now() - datetime.fromisoformat(created_str)).days
            project_age = f"{age}d" if age < 30 else f"{age//30}mo"
        except Exception:
            pass

    # Timeline for sparkline (last 14 days)
    timeline_days: dict[str, int] = {}
    try:
        from datetime import datetime, timedelta
        today = datetime.now().date()
        for e in timeline:
            ts = e.get("ts", "")[:10]
            timeline_days[ts] = timeline_days.get(ts, 0) + 1
    except Exception:
        pass

    return {
        "name":           meta.get("name", path.name),
        "description":    meta.get("description", ""),
        "path":           str(path),
        "model":          meta.get("model") or pcfg.get("model", "—"),
        "planner_model":  pcfg.get("planner_model", ""),
        "coder_model":    pcfg.get("coder_model", ""),
        "vision_model":   pcfg.get("vision_model", ""),
        "fast_model":     pcfg.get("fast_model", ""),
        "theme":          pcfg.get("theme", "dark-gradient"),
        "domain":         pcfg.get("domain", "auto"),
        "created":        created_str[:10],
        "project_age":    project_age,
        "last_generated": last_gen[:16].replace("T", " ") if last_gen else "never",
        "gen_count":      len(gen_events),
        "milestones":     [m.get("label", "") for m in milestones],
        "timeline":       timeline,
        "timeline_days":  timeline_days,
        "pending_files":  pending,
        "slide_count":    slide_count,
        "html_size":      html_size,
        "has_html":       html_exists,
        "has_pdf":        pdf_exists,
        "has_pptx":       bool(pptx_files),
        "html_path":      str(html_path) if html_exists else None,
        "file_types":     ft,
        "git_branch":     git_branch,
        "git_commits":    git_commits,
        "git_last_msg":   git_last_msg,
        "git_last_date":  git_last_date,
    }


def _timeline_strip(events: list[dict]) -> str:
    """Render a compact horizontal timeline of project events."""
    if not events:
        return ""
    items = []
    for e in events[-18:]:  # last 18 events
        ts    = e.get("ts", "")[:16].replace("T", " ")
        etype = e.get("event", "")
        if etype == "milestone":
            label = e.get("label", "milestone")
            items.append(
                f'<div class="tl-item tl-milestone" title="{ts}: {label}">'
                f'<span class="tl-dot"></span>'
                f'<span class="tl-label">★ {label}</span>'
                f'</div>'
            )
        elif etype == "generated":
            model = e.get("model", "")
            items.append(
                f'<div class="tl-item tl-gen" title="{ts}: generated ({model})">'
                f'<span class="tl-dot"></span>'
                f'<span class="tl-label">⚡ generated</span>'
                f'</div>'
            )
        elif etype == "checkpoint":
            n = len(e.get("file_hashes", {}))
            items.append(
                f'<div class="tl-item tl-chk" title="{ts}: {n} files">'
                f'<span class="tl-dot"></span>'
                f'</div>'
            )
        elif etype == "init":
            items.append(
                f'<div class="tl-item tl-init" title="{ts}: project created">'
                f'<span class="tl-dot"></span>'
                f'<span class="tl-label">init</span>'
                f'</div>'
            )
    return f'<div class="timeline-strip">{"".join(items)}</div>'


def _activity_heatmap(timeline_days: dict[str, int]) -> str:
    """14-day activity bar."""
    from datetime import datetime, timedelta
    today = datetime.now().date()
    bars  = []
    for i in range(13, -1, -1):
        day = str(today - timedelta(days=i))
        n   = timeline_days.get(day, 0)
        h   = min(n * 8 + 2, 24)
        cls = "act-high" if n >= 5 else "act-mid" if n >= 2 else "act-low" if n >= 1 else "act-none"
        bars.append(f'<div class="act-bar {cls}" style="height:{h}px" title="{day}: {n} events"></div>')
    return f'<div class="activity">{"".join(bars)}</div>'


def _git_block(branch: str, commits: str, msg: str, date: str) -> str:
    if not branch:
        return ""
    msg_html = f'<div class="git-msg">{msg} <span class="git-date">{date}</span></div>' if msg else ""
    return (
        f'<div class="section-block">'
        f'<div class="section-head">Git</div>'
        f'<div class="git-info">'
        f'<span class="git-branch">⎇ {branch}</span>'
        f'<span class="git-c">{commits} commits</span>'
        f'</div>{msg_html}</div>'
    )


def _card_html(s: dict) -> str:
    name        = s.get("name", "Unnamed")
    desc        = s.get("description", "") or ""
    path        = s.get("path", "")
    domain      = s.get("domain", "auto")
    created     = s.get("created", "")
    project_age = s.get("project_age", "")
    last_gen    = s.get("last_generated", "never")
    gen_count   = s.get("gen_count", 0)
    milestones  = s.get("milestones", [])
    pending     = s.get("pending_files", [])
    slide_count = s.get("slide_count", 0)
    html_size   = s.get("html_size", "")
    has_html    = s.get("has_html", False)
    has_pdf     = s.get("has_pdf", False)
    has_pptx    = s.get("has_pptx", False)
    html_path   = s.get("html_path", "")
    ft          = s.get("file_types", {})
    git_branch  = s.get("git_branch", "")
    git_commits = s.get("git_commits", "")
    git_msg     = s.get("git_last_msg", "")
    git_date    = s.get("git_last_date", "")
    planner     = s.get("planner_model", "")
    coder       = s.get("coder_model", "")
    vision      = s.get("vision_model", "")
    fast        = s.get("fast_model", "")
    model       = s.get("model", "")
    timeline    = s.get("timeline", [])
    tl_days     = s.get("timeline_days", {})

    domain_labels = {"ml": "ML", "software": "Software", "data": "Data", "auto": "Auto", "diff": "Diff"}
    domain_label  = domain_labels.get(domain, domain.title())

    # File counts
    total_files = sum(ft.values())
    file_row = ""
    icons = {"image": ("🖼", "img"), "data": ("📊", "data"), "code": ("💻", "code"), "text": ("📝", "notes")}
    parts = []
    for k, (ico, lbl) in icons.items():
        n = ft.get(k, 0)
        if n:
            parts.append(f'<span class="ftag">{ico} {n} {lbl}</span>')
    if parts:
        file_row = f'<div class="file-row">{"".join(parts)}</div>'

    # Models
    model_rows = []
    if planner: model_rows.append(("Planner", planner))
    if coder:   model_rows.append(("Coder",   coder))
    if vision:  model_rows.append(("Vision",  vision))
    if fast:    model_rows.append(("Fast",    fast))
    if not model_rows and model:
        model_rows.append(("Model", model))
    model_html = "".join(
        f'<div class="model-row"><span class="mr-role">{r}</span><span class="mr-name">{m}</span></div>'
        for r, m in model_rows
    )

    # Output row
    out_parts = []
    if has_html:
        extra = f" · {slide_count}sl · {html_size}" if slide_count else ""
        out_parts.append(f'<span class="out out-html">HTML{extra}</span>')
    if has_pdf:
        out_parts.append('<span class="out out-pdf">PDF</span>')
    if has_pptx:
        out_parts.append('<span class="out out-pptx">PPTX</span>')
    if not out_parts:
        out_parts.append('<span class="out out-none">No output</span>')

    # Milestones
    ms_html = ""
    if milestones:
        tags = "".join(f'<span class="ms-tag">★ {m}</span>' for m in milestones[-5:])
        ms_html = f'<div class="ms-row">{tags}</div>'

    # Pending
    pending_html = ""
    if pending:
        pending_html = f'<div class="pending-bar">⚠ {len(pending)} file{"s" if len(pending)>1 else ""} changed since last generation</div>'

    open_btn = (f'<a class="cta" href="/open?path={html_path}" target="_blank">Open ↗</a>'
                if has_html else "")

    timeline_html = _timeline_strip(timeline)
    activity_html = _activity_heatmap(tl_days)

    return f"""<div class="card" data-domain="{domain}">
  <div class="card-accent domain-{domain}"></div>
  <div class="card-body">

    <div class="card-head">
      <div>
        <div class="card-title">{name}</div>
        <div class="card-desc">{desc[:100] + ("…" if len(desc) > 100 else "")}</div>
      </div>
      <span class="domain-tag dt-{domain}">{domain_label}</span>
    </div>

    <div class="kpi-row">
      <div class="kpi"><span class="kv">{gen_count}</span><span class="kl">generated</span></div>
      <div class="kpi"><span class="kv">{len(milestones)}</span><span class="kl">milestones</span></div>
      <div class="kpi"><span class="kv">{slide_count or "—"}</span><span class="kl">slides</span></div>
      <div class="kpi"><span class="kv">{total_files}</span><span class="kl">files</span></div>
    </div>

    {pending_html}

    <div class="section-block">
      <div class="section-head">Timeline</div>
      {timeline_html}
      <div class="activity-wrap">
        <span class="act-label">14d activity</span>
        {activity_html}
      </div>
    </div>

    {f'<div class="section-block"><div class="section-head">Files</div>{file_row}</div>' if file_row else ""}

    {_git_block(git_branch, git_commits, git_msg, git_date)}

    {f'<div class="section-block"><div class="section-head">Models</div>{model_html}</div>' if model_html else ""}

    {f'<div class="section-block"><div class="section-head">Milestones</div>{ms_html}</div>' if ms_html else ""}

    <div class="card-foot">
      <div class="out-row">{"".join(out_parts)}</div>
      <div class="card-meta-row">
        <span class="meta-created">Created {created}{f" · {project_age} ago" if project_age else ""}</span>
        <span class="meta-gen">Last run {last_gen}</span>
      </div>
      <code class="run-cmd">sarathi join {path.split("/")[-1]}/ --once</code>
      <div class="foot-actions">
        {open_btn}
        <a class="cta-ghost" href="/detail?path={path}">Details</a>
      </div>
    </div>

  </div>
</div>"""


_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --ink0:   #080810;
  --ink1:   #0f0f1e;
  --ink2:   #161628;
  --ink3:   #1e1e38;
  --ink4:   #2a2a4a;
  --dim:    #4a4a6a;
  --muted:  #7a7a9a;
  --fg2:    #a0a0c0;
  --fg:     #d8d8f0;
  --white:  #f0f0ff;
  --blue:   #4fc3f7;
  --purple: #9b7ff4;
  --green:  #3dd68c;
  --amber:  #f5a623;
  --red:    #f06a6a;
  --pink:   #f48fb1;
}

html { font-size: 14px; }

body {
  background: var(--ink0);
  color: var(--fg);
  font-family: 'Inter', system-ui, sans-serif;
  min-height: 100vh;
  line-height: 1.5;
}

/* ── TOP BAR ── */
.topbar {
  height: 52px;
  border-bottom: 1px solid var(--ink3);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(8,8,16,.92);
  backdrop-filter: blur(12px);
}
.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  letter-spacing: -.01em;
  color: var(--white);
}
.logo-mark {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: linear-gradient(135deg, var(--blue), var(--purple));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 800;
  color: #000;
}
.logo-sub { color: var(--dim); font-weight: 400; font-size: .8rem; margin-left: 2px; }

.topbar-right { display: flex; align-items: center; gap: 24px; }
.top-stat { text-align: right; }
.top-stat-val { font-size: 1.1rem; font-weight: 700; color: var(--blue); display: block; line-height: 1; }
.top-stat-lbl { font-size: .68rem; color: var(--dim); text-transform: uppercase; letter-spacing: .06em; }

/* ── TOOLBAR ── */
.toolbar {
  padding: 20px 32px 0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.search {
  width: 280px;
  background: var(--ink2);
  border: 1px solid var(--ink4);
  border-radius: 6px;
  padding: 7px 12px;
  color: var(--fg);
  font-size: .85rem;
  font-family: inherit;
  outline: none;
  transition: border-color .15s;
}
.search:focus { border-color: var(--blue); }
.search::placeholder { color: var(--dim); }

.filter-row { display: flex; gap: 6px; }
.filt {
  padding: 5px 12px;
  border-radius: 5px;
  border: 1px solid var(--ink4);
  background: transparent;
  color: var(--muted);
  font-size: .75rem;
  cursor: pointer;
  transition: all .12s;
  font-family: inherit;
}
.filt:hover, .filt.active { border-color: var(--blue); color: var(--blue); background: rgba(79,195,247,.07); }

/* ── GRID ── */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 16px;
  padding: 20px 32px 60px;
}

/* ── CARD ── */
.card {
  background: var(--ink1);
  border: 1px solid var(--ink3);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: border-color .2s, box-shadow .2s, transform .15s;
  position: relative;
}
.card:hover {
  border-color: var(--ink4);
  box-shadow: 0 8px 40px rgba(0,0,0,.4);
  transform: translateY(-2px);
}

.card-accent {
  height: 2px;
  width: 100%;
}
.domain-ml       { background: linear-gradient(90deg, var(--blue), var(--purple)); }
.domain-software { background: linear-gradient(90deg, var(--green), var(--blue)); }
.domain-data     { background: linear-gradient(90deg, var(--amber), var(--pink)); }
.domain-auto     { background: linear-gradient(90deg, var(--purple), var(--blue)); }
.domain-diff     { background: linear-gradient(90deg, var(--pink), var(--purple)); }

.card-body { padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 14px; flex: 1; }

/* head */
.card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.card-title { font-size: 1rem; font-weight: 600; color: var(--white); letter-spacing: -.01em; }
.card-desc { font-size: .78rem; color: var(--muted); margin-top: 3px; line-height: 1.4; }

.domain-tag {
  flex-shrink: 0;
  font-size: .65rem;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.dt-ml       { background: rgba(79,195,247,.12); color: var(--blue); }
.dt-software { background: rgba(61,214,140,.12); color: var(--green); }
.dt-data     { background: rgba(245,166,35,.12); color: var(--amber); }
.dt-auto     { background: rgba(155,127,244,.12); color: var(--purple); }
.dt-diff     { background: rgba(244,143,177,.12); color: var(--pink); }

/* KPI row */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--ink3);
  border: 1px solid var(--ink3);
  border-radius: 7px;
  overflow: hidden;
}
.kpi {
  background: var(--ink2);
  padding: 9px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.kv { font-size: .95rem; font-weight: 700; color: var(--fg); line-height: 1; }
.kl { font-size: .6rem; color: var(--dim); text-transform: uppercase; letter-spacing: .05em; }

/* Pending */
.pending-bar {
  font-size: .72rem;
  color: var(--amber);
  background: rgba(245,166,35,.08);
  border: 1px solid rgba(245,166,35,.2);
  border-radius: 5px;
  padding: 6px 10px;
}

/* sections */
.section-block { display: flex; flex-direction: column; gap: 6px; }
.section-head {
  font-size: .62rem;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: var(--dim);
  font-weight: 600;
}

/* Timeline strip */
.timeline-strip {
  display: flex;
  align-items: center;
  gap: 0;
  overflow-x: auto;
  padding: 4px 0;
  scrollbar-width: none;
  position: relative;
}
.timeline-strip::-webkit-scrollbar { display: none; }
.timeline-strip::before {
  content: "";
  position: absolute;
  left: 0; right: 0;
  top: 50%;
  height: 1px;
  background: var(--ink4);
  z-index: 0;
}
.tl-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
  margin-right: 12px;
}
.tl-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 1.5px solid;
  background: var(--ink1);
}
.tl-label {
  font-size: .6rem;
  white-space: nowrap;
  color: var(--muted);
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tl-milestone .tl-dot { border-color: var(--amber); background: var(--amber); }
.tl-milestone .tl-label { color: var(--amber); }
.tl-gen .tl-dot { border-color: var(--blue); background: var(--blue); }
.tl-gen .tl-label { color: var(--blue); }
.tl-chk .tl-dot { border-color: var(--ink4); }
.tl-init .tl-dot { border-color: var(--purple); background: var(--purple); }
.tl-init .tl-label { color: var(--purple); }

/* Activity heatmap */
.activity-wrap {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  margin-top: 4px;
}
.act-label { font-size: .58rem; color: var(--dim); white-space: nowrap; }
.activity { display: flex; align-items: flex-end; gap: 2px; height: 24px; }
.act-bar { width: 12px; border-radius: 2px; min-height: 2px; transition: height .3s; }
.act-none { background: var(--ink3); }
.act-low  { background: rgba(79,195,247,.25); }
.act-mid  { background: rgba(79,195,247,.55); }
.act-high { background: var(--blue); }

/* File row */
.file-row { display: flex; flex-wrap: wrap; gap: 5px; }
.ftag {
  font-size: .68rem;
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--ink3);
  color: var(--fg2);
  border: 1px solid var(--ink4);
}

/* Git */
.git-info { display: flex; align-items: center; gap: 10px; }
.git-branch {
  font-size: .72rem;
  color: var(--green);
  font-family: 'JetBrains Mono', monospace;
}
.git-c { font-size: .68rem; color: var(--dim); }
.git-msg {
  font-size: .7rem;
  color: var(--muted);
  margin-top: 3px;
  font-style: italic;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.git-date { color: var(--dim); font-size: .65rem; font-style: normal; }

/* Models */
.model-row { display: flex; justify-content: space-between; align-items: center; padding: 2px 0; }
.mr-role { font-size: .65rem; color: var(--dim); text-transform: uppercase; letter-spacing: .05em; }
.mr-name { font-size: .72rem; color: var(--fg2); font-family: 'JetBrains Mono', monospace; }

/* Milestones */
.ms-row { display: flex; flex-wrap: wrap; gap: 5px; }
.ms-tag {
  font-size: .68rem;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(245,166,35,.08);
  border: 1px solid rgba(245,166,35,.18);
  color: var(--amber);
}

/* Card footer */
.card-foot { margin-top: auto; display: flex; flex-direction: column; gap: 8px; }

.out-row { display: flex; gap: 5px; flex-wrap: wrap; }
.out {
  font-size: .65rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: .03em;
}
.out-html { background: rgba(61,214,140,.1); color: var(--green); border: 1px solid rgba(61,214,140,.2); }
.out-pdf  { background: rgba(79,195,247,.1); color: var(--blue);  border: 1px solid rgba(79,195,247,.2); }
.out-pptx { background: rgba(245,166,35,.1); color: var(--amber); border: 1px solid rgba(245,166,35,.2); }
.out-none { background: rgba(240,106,106,.08); color: var(--red); border: 1px solid rgba(240,106,106,.15); font-style: italic; }

.card-meta-row { display: flex; justify-content: space-between; }
.meta-created, .meta-gen { font-size: .65rem; color: var(--dim); }

.run-cmd {
  font-family: 'JetBrains Mono', monospace;
  font-size: .65rem;
  color: var(--dim);
  background: var(--ink2);
  border: 1px solid var(--ink3);
  border-radius: 4px;
  padding: 4px 8px;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.run-cmd:hover { border-color: var(--ink4); color: var(--fg2); }

.foot-actions { display: flex; gap: 6px; }
.cta {
  flex: 1;
  padding: 7px 14px;
  background: var(--blue);
  color: #000;
  border-radius: 5px;
  text-decoration: none;
  font-size: .75rem;
  font-weight: 600;
  text-align: center;
  transition: opacity .15s;
}
.cta:hover { opacity: .85; }
.cta-ghost {
  padding: 7px 14px;
  border: 1px solid var(--ink4);
  color: var(--muted);
  border-radius: 5px;
  text-decoration: none;
  font-size: .75rem;
  font-weight: 500;
  text-align: center;
  transition: border-color .15s, color .15s;
}
.cta-ghost:hover { border-color: var(--fg2); color: var(--fg); }

/* Empty */
.empty {
  grid-column: 1/-1;
  padding: 80px 40px;
  text-align: center;
  color: var(--dim);
}
.empty h2 { color: var(--muted); margin-bottom: 8px; font-weight: 500; }

/* FAB */
.fab {
  position: fixed;
  bottom: 24px; right: 24px;
  width: 44px; height: 44px;
  background: var(--ink3);
  border: 1px solid var(--ink4);
  border-radius: 50%;
  color: var(--fg2);
  font-size: 1.1rem;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background .15s, color .15s;
}
.fab:hover { background: var(--ink4); color: var(--fg); }

.card.hidden { display: none; }
"""

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sarathi Portfolio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>CSS_PLACEHOLDER</style>
</head>
<body>

<div class="topbar">
  <div class="logo">
    <div class="logo-mark">S</div>
    Sarathi <span class="logo-sub">/ portfolio</span>
  </div>
  <div class="topbar-right">
    <div class="top-stat"><span class="top-stat-val" id="s-proj">—</span><span class="top-stat-lbl">Projects</span></div>
    <div class="top-stat"><span class="top-stat-val" id="s-ms">—</span><span class="top-stat-lbl">Milestones</span></div>
    <div class="top-stat"><span class="top-stat-val" id="s-gen">—</span><span class="top-stat-lbl">Generated</span></div>
    <div class="top-stat"><span class="top-stat-val" id="s-slides">—</span><span class="top-stat-lbl">Slides</span></div>
  </div>
</div>

<div class="toolbar">
  <input class="search" id="search" placeholder="Search projects…" oninput="filter(this.value)">
  <div class="filter-row">
    <button class="filt active" onclick="setDomain('')">All</button>
    <button class="filt" onclick="setDomain('software')">Software</button>
    <button class="filt" onclick="setDomain('ml')">ML</button>
    <button class="filt" onclick="setDomain('data')">Data</button>
  </div>
</div>

<div class="grid" id="grid">
CARDS_PLACEHOLDER
</div>

<button class="fab" onclick="location.reload()" title="Refresh">↻</button>

<script>
const cards = [...document.querySelectorAll('.card')];
let activeDomain = '';

function calcStats() {
  const proj   = cards.length;
  const ms     = cards.reduce((n,c) => n + c.querySelectorAll('.ms-tag').length, 0);
  const gen    = cards.reduce((n,c) => n + (parseInt(c.querySelector('.kv')?.textContent)||0), 0);
  const slides = cards.reduce((n,c) => {
    const kvs = c.querySelectorAll('.kv');
    return n + (parseInt(kvs[2]?.textContent)||0);
  }, 0);
  document.getElementById('s-proj').textContent   = proj;
  document.getElementById('s-ms').textContent     = ms;
  document.getElementById('s-gen').textContent    = gen;
  document.getElementById('s-slides').textContent = slides || '—';
}
calcStats();

function applyFilters(q, domain) {
  cards.forEach(c => {
    const textMatch   = !q || c.textContent.toLowerCase().includes(q.toLowerCase());
    const domainMatch = !domain || c.dataset.domain === domain;
    c.classList.toggle('hidden', !textMatch || !domainMatch);
  });
}

function filter(q) { applyFilters(q, activeDomain); }

function setDomain(d) {
  activeDomain = d;
  document.querySelectorAll('.filt').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  applyFilters(document.getElementById('search').value, d);
}

// Copy run command on click
document.querySelectorAll('.run-cmd').forEach(el => {
  el.title = 'Click to copy';
  el.onclick = () => {
    navigator.clipboard.writeText(el.textContent.trim());
    const old = el.textContent;
    el.textContent = 'Copied!';
    setTimeout(() => el.textContent = old, 1200);
  };
});
</script>
</body>
</html>"""


def serve(port: int = 7432, extra_dirs: list[str] | None = None) -> None:
    from flask import Flask, request, redirect, Response
    import webbrowser, threading

    app = Flask(__name__)

    @app.route("/")
    def index():
        projects: dict[str, dict] = {}
        for key, info in _load_registry().items():
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
            cards = '<div class="empty"><h2>No projects yet</h2><p>Run <code>sarathi init</code> to create one.</p></div>'
        else:
            cards = "\n".join(_card_html(s) for s in projects.values())

        html = (_HTML_TEMPLATE
                .replace("CARDS_PLACEHOLDER", cards)
                .replace("CSS_PLACEHOLDER", _CSS))
        return Response(html, content_type="text/html")

    @app.route("/open")
    def open_file():
        path = request.args.get("path", "")
        if path and Path(path).exists():
            return redirect(f"file://{path}")
        return "Not found", 404

    @app.route("/detail")
    def detail():
        path = request.args.get("path", "")
        p = Path(path)
        if not p.exists():
            return "Not found", 404
        s = _project_summary(p)
        return Response(
            f"<pre style='background:#0f0f1e;color:#d8d8f0;padding:24px;font-family:monospace;min-height:100vh'>"
            f"{json.dumps(s, indent=2, default=str)}</pre>",
            content_type="text/html",
        )

    url = f"http://localhost:{port}"
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"\n  Sarathi Portfolio  →  {url}\n  Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
