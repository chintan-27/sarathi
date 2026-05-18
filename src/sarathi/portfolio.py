from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

_REGISTRY = Path.home() / ".config" / "sarathi" / "projects.json"

# ── Quotes (rotates daily by date seed) ──────────────────────────────────────

_QUOTES = [
    ("The purpose of computing is insight, not numbers.", "Richard Hamming", "ml"),
    ("Make it work, make it right, make it fast.", "Kent Beck", "software"),
    ("Torture the data and it will confess to anything.", "Ronald Coase", "data"),
    ("Programs must be written for people to read.", "Abelson & Sussman", "software"),
    ("The goal is to turn data into information, and information into insight.", "Carly Fiorina", "data"),
    ("It's not that I'm so smart, I just stay with problems longer.", "Albert Einstein", "ml"),
    ("First, solve the problem. Then, write the code.", "John Johnson", "software"),
    ("In God we trust. All others must bring data.", "W. Edwards Deming", "data"),
    ("A year from now you may wish you had started today.", "Karen Lamb", "ml"),
    ("Any sufficiently advanced technology is indistinguishable from magic.", "Arthur C. Clarke", "software"),
    ("Without data, you're just another person with an opinion.", "W. Edwards Deming", "data"),
    ("The best way to predict the future is to invent it.", "Alan Kay", "software"),
    ("Intelligence is the ability to adapt to change.", "Stephen Hawking", "ml"),
    ("Simplicity is the soul of efficiency.", "Austin Freeman", "software"),
    ("Data is the new oil.", "Clive Humby", "data"),
]

_TILE_COLORS = ["mustard", "ember", "dusk", "olive", "char", "mint", "candy", "sky", "lilac"]

_DOMAIN_COLOR_MAP = {
    "ml":       ["mustard", "ember", "lilac"],
    "software": ["dusk", "char", "sky"],
    "data":     ["olive", "mint", "candy"],
    "auto":     ["mustard", "dusk", "mint"],
    "diff":     ["candy", "ember", "dusk"],
}


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


# ── Data extraction ───────────────────────────────────────────────────────────

def _git(cmd: list[str], cwd: str, timeout: int = 4) -> str:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True,
                              text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def _get_git_details(project_dir: Path) -> dict:
    cwd = str(project_dir)
    branch = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    total_commits = _git(["git", "rev-list", "--count", "HEAD"], cwd)

    # Recent commits with hash|subject|date|+added|-deleted
    log_raw = _git(["git", "log", "-15", "--format=%H|%s|%ad", "--date=short"], cwd)
    commits = []
    for line in log_raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0][:7], "msg": parts[1][:70], "date": parts[2], "added": 0, "deleted": 0})

    # Line stats per commit (best-effort)
    stat_raw = _git(["git", "log", "-15", "--format=COMMIT", "--shortstat"], cwd)
    stat_blocks = stat_raw.split("COMMIT")
    for i, block in enumerate(stat_blocks[1:len(commits)+1]):
        import re
        m_add = re.search(r"(\d+) insertion", block)
        m_del = re.search(r"(\d+) deletion", block)
        if i < len(commits):
            commits[i]["added"] = int(m_add.group(1)) if m_add else 0
            commits[i]["deleted"] = int(m_del.group(1)) if m_del else 0

    # Top changed files
    name_raw = _git(
        ["git", "log", "--format=", "--name-only", "HEAD~50..HEAD"],
        cwd, timeout=5
    )
    file_counts: dict[str, int] = {}
    for fn in name_raw.splitlines():
        fn = fn.strip()
        if fn:
            file_counts[fn] = file_counts.get(fn, 0) + 1
    top_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Weekly commit sparkline (last 12 weeks)
    weekly: list[int] = []
    today = datetime.now().date()
    for w in range(11, -1, -1):
        since = str(today - timedelta(weeks=w+1))
        until = str(today - timedelta(weeks=w))
        n = _git(
            ["git", "rev-list", "--count", f"--after={since}", f"--before={until}", "HEAD"],
            cwd
        )
        weekly.append(int(n) if n.isdigit() else 0)

    return {
        "branch": branch,
        "total_commits": total_commits,
        "commits": commits,
        "top_files": [{"name": f, "count": c} for f, c in top_files],
        "weekly_spark": weekly,
    }


def _get_file_details(project_dir: Path) -> dict:
    from . import scanner as sc
    skip = sc.SKIP_DIRS | {"output"}
    groups: dict[str, list[dict]] = {"images": [], "data": [], "code": [], "text": []}
    ext_to_group = {
        **{e: "images" for e in sc.IMAGE_EXTS | sc.SVG_EXTS},
        **{e: "data"   for e in sc.DATA_EXTS},
        **{e: "text"   for e in sc.TEXT_EXTS},
        **{e: "code"   for e in sc.CODE_EXTS | {sc.NOTEBOOK_EXT}},
    }
    for f in sorted(project_dir.rglob("*")):
        if not f.is_file():
            continue
        if any(part in skip for part in f.parts):
            continue
        if f.name.startswith("."):
            continue
        ext = f.suffix.lower()
        group = ext_to_group.get(ext)
        if not group:
            continue
        try:
            size = f.stat().st_size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%b %d")
            size_str = f"{size/1024:.0f} KB" if size < 1_000_000 else f"{size/1_000_000:.1f} MB"
            info: dict = {
                "name": f.name,
                "rel": str(f.relative_to(project_dir)),
                "size": size_str,
                "mtime": mtime,
                "ext": ext,
            }
            if group == "code":
                try:
                    lines = f.read_text(encoding="utf-8", errors="replace").count("\n")
                    info["lines"] = lines
                except Exception:
                    info["lines"] = 0
            elif group == "images":
                info["lines"] = 0
            groups[group].append(info)
        except Exception:
            pass
    return groups


def _get_csv_stats(path: Path) -> dict | None:
    try:
        import pandas as pd
        df = pd.read_csv(path, nrows=500)
        cols = list(df.columns)
        nulls = int(df.isnull().sum().sum())
        rows, ncols = df.shape
        num_cols = df.select_dtypes(include="number").columns.tolist()
        stats = {}
        for c in num_cols[:4]:
            stats[c] = {
                "mean": f"{df[c].mean():.2f}" if not df[c].isna().all() else "—",
                "std":  f"{df[c].std():.2f}"  if not df[c].isna().all() else "—",
            }
        null_cols = [c for c in df.columns if df[c].isnull().any()]
        return {
            "name": path.name,
            "shape": f"{rows:,} rows × {ncols} cols",
            "cols": cols[:12],
            "nulls": nulls,
            "null_cols": null_cols[:3],
            "stats": stats,
        }
    except Exception:
        return None


def _compute_evolution_level(s: dict) -> tuple[int, str]:
    files = sum(s.get("file_types", {}).values())
    gens  = s.get("gen_count", 0)
    ms    = len(s.get("milestones", []))
    has_html = s.get("has_html", False)
    if files < 5 or gens == 0:
        return 1, "Seed"
    if ms >= 4 and gens >= 5 and has_html:
        return 4, "Presentation-ready"
    if ms >= 2 and gens >= 3:
        return 3, "Story-rich"
    return 2, "Active"


def _project_color(name: str, domain: str, idx: int) -> str:
    palette = _DOMAIN_COLOR_MAP.get(domain, _TILE_COLORS)
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return palette[(h + idx) % len(palette)]


def _compute_achievements(all_summaries: list[dict]) -> list[dict]:
    total_ms  = sum(len(s.get("milestones", [])) for s in all_summaries)
    total_gen = sum(s.get("gen_count", 0) for s in all_summaries)
    best_toks = max((s.get("best_tok_s") or 0 for s in all_summaries), default=0)
    n_proj    = len(all_summaries)
    streak    = _compute_streak(all_summaries)

    # Night owl: any generated event between 23:00–04:00
    def _night_owl():
        for s in all_summaries:
            for e in s.get("timeline", []):
                if e.get("event") == "generated":
                    hour = int(e.get("ts", "T00")[-8:-6] or 0)
                    if hour >= 23 or hour < 4:
                        return True
        return False

    return [
        {"glyph": "✦", "name": "First Generation",  "desc": "Generated your first slide deck.",           "unlocked": total_gen >= 1},
        {"glyph": "⊞", "name": "10 Milestones",      "desc": "Marked ten milestones across all projects.", "unlocked": total_ms >= 10},
        {"glyph": "⚡", "name": "Speed Demon",        "desc": f"Hit > 50 tok/s  ·  best: {best_toks:.0f} tok/s", "unlocked": best_toks > 50},
        {"glyph": "☾", "name": "Night Owl",           "desc": "Generated a deck after midnight.",           "unlocked": _night_owl()},
        {"glyph": "⌘", "name": "Archivist",           "desc": "Maintained five or more projects.",          "unlocked": n_proj >= 5},
        {"glyph": "⌖", "name": "Streak 7d",           "desc": f"Generate seven days running. {min(streak,7)}/7.", "unlocked": streak >= 7},
        {"glyph": "✕", "name": "Personal Best",       "desc": "Beat your own best generation time.",        "unlocked": total_gen >= 3},
        {"glyph": "◐", "name": "New Project",         "desc": "Seed a new project this week.",              "unlocked": _check_new_this_week(all_summaries)},
    ]


def _compute_streak(all_summaries: list[dict]) -> int:
    all_days: set[str] = set()
    for s in all_summaries:
        for e in s.get("timeline", []):
            all_days.add(e.get("ts", "")[:10])
    today = datetime.now().date()
    streak = 0
    for i in range(365):
        d = str(today - timedelta(days=i))
        if d in all_days:
            streak += 1
        else:
            break
    return streak


def _check_new_this_week(all_summaries: list[dict]) -> bool:
    cutoff = str(datetime.now().date() - timedelta(days=7))
    for s in all_summaries:
        if s.get("created", "") >= cutoff:
            return True
    return False


def _compute_weekly_wrapped(all_summaries: list[dict]) -> dict:
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()[:10]
    slides_week = 0
    gen_week = 0
    model_counts: dict[str, int] = {}
    day_counts: dict[str, int] = {}
    for s in all_summaries:
        for e in s.get("timeline", []):
            ts = e.get("ts", "")
            if ts[:10] < cutoff:
                continue
            day_counts[ts[:10]] = day_counts.get(ts[:10], 0) + 1
            if e.get("event") == "generated":
                gen_week += 1
                slides_week += e.get("slide_count", 0)
                m = e.get("model", "")
                if m:
                    model_counts[m] = model_counts.get(m, 0) + 1
    fav_model = max(model_counts, key=lambda k: model_counts[k]) if model_counts else "—"
    best_day = "—"
    if day_counts:
        bd = max(day_counts, key=lambda d: day_counts[d])
        best_day = datetime.fromisoformat(bd).strftime("%a")
    streak = _compute_streak(all_summaries)
    return {
        "slides": slides_week,
        "gens": gen_week,
        "fav_model": fav_model.split(":")[0] if ":" in fav_model else fav_model,
        "best_day": best_day,
        "streak": streak,
    }


def _compute_insight(all_summaries: list[dict], wrapped: dict) -> str:
    pending = sum(1 for s in all_summaries if s.get("pending_files"))
    streak = wrapped.get("streak", 0)
    gens_week = wrapped.get("gens", 0)
    fav_model = wrapped.get("fav_model", "")
    best_tok_s = max((s.get("best_tok_s") or 0 for s in all_summaries), default=0)

    if pending > 0:
        return (f"<em>{pending} project{'s' if pending > 1 else ''}</em> "
                f"{'have' if pending > 1 else 'has'} files changed — decks may be stale.")
    if streak >= 5:
        return (f"You're on a <em>{streak}-day streak</em> — closing in on your "
                f"<em>best week yet</em> with {gens_week} generations.")
    if best_tok_s > 50:
        return (f"<code>{fav_model}</code> is your <em>fastest model</em> "
                f"at <em>{best_tok_s:.0f} tok/s</em> — keep using it for quick iterations.")
    if gens_week >= 5:
        return (f"You've generated <em>{gens_week} times</em> this week "
                f"across {len(all_summaries)} projects — great momentum.")
    return (f"<em>{len(all_summaries)} projects</em> tracked · "
            f"<code>{fav_model or 'no model yet'}</code> is your current workhorse.")


def _get_ollama_status() -> dict:
    """Check backend status — cloud API if configured, otherwise Ollama."""
    from . import config as _cfg
    from . import keystore as _ks

    # Load global config (use a dummy path — load_project_config merges global first)
    try:
        global_cfg = _cfg.load_project_config(Path.home())
    except Exception:
        global_cfg = {}

    if global_cfg.get("backend") == "cloud" and global_cfg.get("cloud_api_url"):
        url = global_cfg["cloud_api_url"]
        raw_key = global_cfg.get("cloud_api_key", "")
        key = _ks.decrypt(raw_key) if raw_key else ""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key, base_url=url)
            models_resp = client.models.list()
            first_model = models_resp.data[0].id if models_resp.data else None
            return {
                "running": True,
                "backend": "cloud",
                "loaded_model": first_model,
                "ram_gb": 0,
                "url": url,
            }
        except Exception:
            return {
                "running": False,
                "backend": "cloud",
                "loaded_model": None,
                "ram_gb": 0,
                "url": url,
            }

    # Default: Ollama
    try:
        import ollama
        ps = ollama.ps()
        models = getattr(ps, "models", []) or []
        if models:
            m = models[0]
            name = getattr(m, "model", "unknown")
            size_vram = getattr(m, "size_vram", 0) or 0
            size = getattr(m, "size", 0) or 0
            ram_bytes = size_vram or size
            ram_gb = ram_bytes / 1_073_741_824
            return {"running": True, "backend": "ollama", "loaded_model": name, "ram_gb": round(ram_gb, 1)}
        return {"running": True, "backend": "ollama", "loaded_model": None, "ram_gb": 0}
    except Exception:
        return {"running": False, "backend": "ollama", "loaded_model": None, "ram_gb": 0}


def _project_summary(project_dir: Path) -> dict:
    from . import tracker as trk
    from . import config as cfg

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
    bests       = trk.get_personal_bests(path)
    status      = trk.read_status(path)
    pid_info    = trk.read_pid(path)

    html_path   = path / "output" / "presentation.html"
    pdf_path    = path / "output" / "presentation.pdf"
    html_exists = html_path.exists()
    pdf_exists  = pdf_path.exists()
    pptx_files  = list((path / "output").glob("*.pptx")) if (path / "output").exists() else []

    slide_count = 0
    html_size   = ""
    if html_exists:
        try:
            import re
            txt  = html_path.read_text(encoding="utf-8", errors="replace")
            slide_count = len(re.findall(r"<section", txt, re.IGNORECASE))
            sz   = html_path.stat().st_size
            html_size = f"{sz/1024:.0f} KB" if sz < 1_000_000 else f"{sz/1_000_000:.1f} MB"
        except Exception:
            pass

    try:
        from . import scanner as sc
        files = sc.scan(path)
        ft: dict[str, int] = {}
        for f in files:
            ft[f.type] = ft.get(f.type, 0) + 1
    except Exception:
        ft = {}

    created_str = meta.get("created", "")
    project_age = ""
    if created_str:
        try:
            age = (datetime.now() - datetime.fromisoformat(created_str)).days
            project_age = f"{age}d" if age < 30 else f"{age//30}mo"
        except Exception:
            pass

    # 14-day activity for sparkline
    timeline_days: dict[str, int] = {}
    spark_data: list[int] = []
    for e in timeline:
        ts = e.get("ts", "")[:10]
        timeline_days[ts] = timeline_days.get(ts, 0) + 1
    today = datetime.now().date()
    for i in range(13, -1, -1):
        d = str(today - timedelta(days=i))
        spark_data.append(timeline_days.get(d, 0))

    # Narrative from last generation event
    narrative = ""
    for e in reversed(gen_events[-3:]):
        slides = e.get("slide_count", 0)
        model  = e.get("model", "")
        dur    = e.get("duration_s", 0)
        ts     = e.get("ts", "")[:16].replace("T", " ")
        if slides:
            narrative = f"Generated {slides}-slide deck ({model} · {dur:.0f}s) · {ts}"
            break
    if not narrative:
        chk = [e for e in reversed(timeline) if e.get("event") == "checkpoint"]
        if chk:
            narrative = f"Watching files · last checkpoint {chk[0].get('ts','')[:16].replace('T',' ')}"

    git_branch = git_commits = git_last_msg = git_last_date = ""
    try:
        cwd = str(path)
        git_branch  = _git(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
        git_commits = _git(["git", "rev-list", "--count", "HEAD"], cwd)
        last_log    = _git(["git", "log", "-1", "--format=%s|%ad", "--date=short"], cwd)
        if "|" in last_log:
            git_last_msg, git_last_date = last_log.split("|", 1)
            git_last_msg = git_last_msg[:55]
    except Exception:
        pass

    evo_level, evo_label = _compute_evolution_level({
        "file_types": ft, "gen_count": len(gen_events),
        "milestones": milestones, "has_html": html_exists,
    })

    # Days dormant
    dormant_days = 0
    last_activity: str | None = None
    if timeline:
        last_activity = max(e.get("ts", "") for e in timeline)
    if last_activity:
        try:
            dormant_days = (datetime.now() - datetime.fromisoformat(last_activity)).days
        except Exception:
            pass

    return {
        "name":           meta.get("name", path.name),
        "description":    meta.get("description", ""),
        "goal":           meta.get("goal", ""),
        "tags":           meta.get("tags") or [],
        "status":         meta.get("status", "active"),
        "repo_url":       meta.get("repo_url", ""),
        "notes_url":      meta.get("notes_url", ""),
        "team":           meta.get("team", "solo"),
        "path":           str(path),
        "model":          meta.get("model") or pcfg.get("model", "—"),
        "planner_model":  pcfg.get("planner_model", ""),
        "coder_model":    pcfg.get("coder_model", ""),
        "vision_model":   pcfg.get("vision_model", ""),
        "fast_model":     pcfg.get("fast_model", ""),
        "theme":          pcfg.get("theme", "dark-gradient"),
        "domain":         meta.get("domain") or pcfg.get("domain", "auto"),
        "created":        created_str[:10],
        "project_age":    project_age,
        "last_generated": last_gen[:16].replace("T", " ") if last_gen else "never",
        "gen_count":      len(gen_events),
        "gen_events":     gen_events[-10:],
        "milestones":     [m.get("label", "") for m in milestones],
        "milestones_full": milestones,
        "timeline":       timeline,
        "timeline_days":  timeline_days,
        "spark_data":     spark_data,
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
        "evo_level":      evo_level,
        "evo_label":      evo_label,
        "narrative":      narrative,
        "dormant_days":   dormant_days,
        "best_tok_s":     bests.get("best_tok_s"),
        "fastest_s":      bests.get("fastest_s"),
        "largest_slides": bests.get("largest_slides"),
        "gen_status":     status,
        "pid_info":       pid_info,
    }


# ── SVG helpers ───────────────────────────────────────────────────────────────

def _render_spark(values: list[int], ink: str = "rgba(0,0,0,.7)") -> str:
    if not values or max(values, default=0) == 0:
        return f'<svg class="spark" viewBox="0 0 200 28" preserveAspectRatio="none"></svg>'
    w, h = 200, 28
    mx = max(values)
    step = w / max(len(values) - 1, 1)
    pts = [(i * step, h - (v / mx) * (h - 3) - 1) for i, v in enumerate(values)]
    path = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    area = path + f" L{w},{h} L0,{h} Z"
    lx, ly = pts[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" style="color:{ink}">'
        f'<path class="area" d="{area}"></path>'
        f'<path class="line" d="{path}"></path>'
        f'<circle class="dot" cx="{lx-2:.1f}" cy="{ly:.1f}" r="2.5"></circle>'
        f'</svg>'
    )


def _render_evo_dots(level: int) -> str:
    def _dot(i: int) -> str:
        cls = ' class="on"' if i <= level else ""
        return f"<i{cls}></i>"
    dots = "".join(_dot(i) for i in range(1, 5))
    return f'<span class="evo-dots">{dots}</span>'


def _heatmap_html(timeline_days: dict[str, int]) -> str:
    today = datetime.now().date()
    # Build 52w × 7d grid (Sunday-first)
    start = today - timedelta(weeks=52)
    # Align to nearest Sunday
    start = start - timedelta(days=start.weekday() + 1)
    cols = []
    for w in range(52):
        col_cells = []
        for d in range(7):
            day = str(start + timedelta(weeks=w, days=d))
            n = timeline_days.get(day, 0)
            if n == 0:
                lvl = ""
            elif n == 1:
                lvl = "l1"
            elif n <= 3:
                lvl = "l2"
            elif n <= 6:
                lvl = "l3"
            else:
                lvl = "l4"
            col_cells.append(f'<div class="heat-cell {lvl}" title="{day}: {n}"></div>')
        cols.append(f'<div class="heat-col">{"".join(col_cells)}</div>')
    return f'<div class="heatmap">{"".join(cols)}</div>'


def _feed_html(timeline: list[dict]) -> str:
    glyphs = {
        "generated":  "⚡",
        "milestone":  "★",
        "checkpoint": "↻",
        "init":       "◉",
        "file_added": "✎",
    }
    items = []
    for e in reversed(timeline[-20:]):
        etype = e.get("event", "")
        ts    = e.get("ts", "")[:16].replace("T", " ")
        g     = glyphs.get(etype, "·")
        if etype == "generated":
            slides = e.get("slide_count", 0)
            model  = e.get("model", "")
            dur    = e.get("duration_s", 0)
            tps    = e.get("tok_s", 0)
            body   = (f'Generated <em>{slides}-slide deck</em> '
                      f'(<code>{model}</code> · {dur:.0f}s'
                      + (f' · {tps:.0f} tok/s' if tps else '') + ').')
        elif etype == "milestone":
            label = e.get("label", "milestone")
            n     = len(e.get("file_hashes", {}))
            body  = f'Milestone <em>"{label}"</em> marked — {n} files at this point.'
        elif etype == "checkpoint":
            n = len(e.get("file_hashes", {}))
            body = f'Auto-checkpoint — {n} files hashed.'
        elif etype == "init":
            body = "Project initialized."
        else:
            f = e.get("file", "")
            body = f'File changed: <code>{f}</code>.' if f else "Event logged."
        items.append(
            f'<div class="feed-item">'
            f'<div class="feed-glyph">{g}</div>'
            f'<div class="feed-body">{body}</div>'
            f'<div class="feed-date">{ts}</div>'
            f'</div>'
        )
    return "".join(items)


def _filebar_html(top_files: list[dict]) -> str:
    if not top_files:
        return "<p style='opacity:.5;font-size:11px'>No git history yet.</p>"
    mx = max(f["count"] for f in top_files)
    rows = []
    for tf in top_files:
        pct = int(tf["count"] / mx * 100)
        rows.append(
            f'<div class="filebar-row">'
            f'<span class="name">{tf["name"]}</span>'
            f'<div class="bar"><div style="width:{pct}%"></div></div>'
            f'<span>{tf["count"]}</span>'
            f'</div>'
        )
    return f'<div class="filebar">{"".join(rows)}</div>'


def _model_chart_html(gen_events: list[dict]) -> str:
    model_tps: dict[str, list[float]] = {}
    for e in gen_events:
        m = e.get("model", "")
        t = e.get("tok_s", 0)
        if m and t:
            model_tps.setdefault(m, []).append(t)
    if not model_tps:
        return ""
    avgs = {m: sum(v)/len(v) for m, v in model_tps.items()}
    mx = max(avgs.values())
    rows = []
    roles = ["planner", "coder", "vision", "fast"]
    for i, (m, avg) in enumerate(sorted(avgs.items(), key=lambda x: -x[1])):
        role = roles[i % len(roles)]
        pct = int(avg / mx * 100)
        rows.append(
            f'<div class="mc-row {role}">'
            f'<span><div class="name">{m}</div><div class="role">{role}</div></span>'
            f'<div class="barwrap"><div style="width:{pct}%"></div></div>'
            f'<div class="val">{avg:.0f}</div>'
            f'</div>'
        )
    return f'<div class="model-chart">{"".join(rows)}</div>'


def _milestone_timeline_html(milestones_full: list[dict]) -> str:
    if not milestones_full:
        return "<p style='opacity:.5;font-size:11px'>No milestones yet.</p>"
    items = []
    prev_date: datetime | None = None
    for ms in milestones_full:
        label = ms.get("label", "milestone")
        ts    = ms.get("ts", "")
        n     = len(ms.get("file_hashes", {}))
        try:
            dt  = datetime.fromisoformat(ts)
            d_str = dt.strftime("%b %d")
            gap = ""
            if prev_date:
                diff = (dt - prev_date).days
                gap = f'<span class="gap">+{diff}d gap</span>'
            prev_date = dt
        except Exception:
            d_str = ts[:10]
            gap = ""
        items.append(
            f'<div class="ms">'
            f'<div class="ms-date">{d_str}</div>'
            f'<div class="ms-title"><em>{label}</em></div>'
            f'<div class="ms-meta"><span>{n} files</span>{gap}</div>'
            f'</div>'
        )
    return f'<div class="timeline">{"".join(items)}</div>'


def _file_browser_html(file_details: dict) -> str:
    type_glyphs = {"images": "▦", "data": "⎈", "code": "{ }", "text": "¶"}
    type_cls    = {"images": "", "data": "data", "code": "code", "text": "text"}
    parts = []
    for gtype, files in file_details.items():
        if not files:
            continue
        label = gtype.title()
        glyph = type_glyphs.get(gtype, "·")
        cls   = type_cls.get(gtype, "")
        rows  = []
        for f in files[:8]:
            shape = ""
            if gtype == "code":
                shape = f'{f.get("lines", 0):,} lines · {f.get("ext","").lstrip(".")}'
            elif gtype == "data":
                shape = f.get("shape", "")
            name  = f.get("name", "")
            size  = f.get("size", "")
            rows.append(
                f'<div class="file-row {cls}">'
                f'<div class="thumb">{glyph}</div>'
                f'<span class="name">{name}</span>'
                f'<span class="shape">{shape}</span>'
                f'<span class="size">{size}</span>'
                f'</div>'
            )
        total = len(files)
        extra = f" + {total-8} more" if total > 8 else ""
        parts.append(
            f'<div class="file-group">'
            f'<h4>— {label} · {total}{extra}</h4>'
            f'<div class="file-list">{"".join(rows)}</div>'
            f'</div>'
        )
    return "".join(parts) or "<p style='opacity:.5;font-size:11px'>No files scanned.</p>"


def _data_insights_html(file_details: dict, project_dir: Path) -> str:
    cards = []
    for fi in file_details.get("data", [])[:4]:
        if not fi["name"].endswith(".csv"):
            continue
        stats = _get_csv_stats(project_dir / fi["rel"])
        if not stats:
            continue
        col_tags = "".join(f'<span class="ct">{c}</span>' for c in stats["cols"][:8])
        stat_rows = "".join(
            f'<div><div class="lbl">{c} μ±σ</div><div>{v["mean"]} ± {v["std"]}</div></div>'
            for c, v in stats["stats"].items()
        )
        null_note = ""
        if stats["nulls"] > 0:
            null_note = f'<div><div class="lbl">nulls</div><div>{stats["nulls"]} in {", ".join(stats["null_cols"])}</div></div>'
        cards.append(
            f'<div class="data-card">'
            f'<h4>{stats["name"]}</h4>'
            f'<div class="shape">{stats["shape"]}</div>'
            f'<div class="cols">{col_tags}</div>'
            f'<div class="stats">{stat_rows}{null_note}</div>'
            f'</div>'
        )
    return f'<div class="data-cards">{"".join(cards)}</div>' if cards else ""


def _gen_table_html(gen_events: list[dict]) -> str:
    if not gen_events:
        return "<p style='opacity:.5;font-size:11px;color:var(--paper)'>No generations yet.</p>"
    fastest_i = min(range(len(gen_events)), key=lambda i: gen_events[i].get("duration_s") or 9999)
    rows = []
    for i, e in enumerate(reversed(gen_events[-10:])):
        ts    = e.get("ts", "")[:10]
        model = e.get("model", "—")
        mode  = e.get("mode", "—")
        tps   = e.get("tok_s", 0)
        dur   = e.get("duration_s", 0)
        slides = e.get("slide_count", 0)
        cls = ' class="fastest"' if i == fastest_i else ""
        rows.append(
            f'<tr{cls}>'
            f'<td>{ts}</td>'
            f'<td><span class="tag">{model}</span></td>'
            f'<td>{mode}</td>'
            f'<td class="num">{tps:.0f}</td>'
            f'<td>{dur:.0f}s</td>'
            f'<td>{slides or "—"}</td>'
            f'</tr>'
        )
    return (
        f'<table class="gen-table"><thead><tr>'
        f'<th>Date</th><th>Model</th><th>Mode</th><th>tok/s</th><th>Dur</th><th>Slides</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


# ── Card rendering ────────────────────────────────────────────────────────────

def _card_html(s: dict, color: str, layout: str, is_display: bool) -> str:
    name        = s.get("name", "Unnamed")
    desc        = s.get("description", "") or ""
    goal        = s.get("goal", "") or ""
    tags        = s.get("tags") or []
    status      = s.get("status", "active")
    repo_url    = s.get("repo_url", "")
    path        = s.get("path", "")
    domain      = s.get("domain", "auto").upper()
    pending     = s.get("pending_files", [])
    dormant     = s.get("dormant_days", 0)
    evo_level   = s.get("evo_level", 1)
    evo_label   = s.get("evo_label", "Seed")
    kpi_files   = sum(s.get("file_types", {}).values())
    kpi_slides  = s.get("slide_count", 0)
    kpi_ms      = len(s.get("milestones", []))
    age         = s.get("project_age", "—")
    spark       = s.get("spark_data", [0]*14)
    narrative   = s.get("narrative", "No activity yet.")
    git_branch  = s.get("git_branch", "")
    git_commits = s.get("git_commits", "—")
    git_msg     = s.get("git_last_msg", "")
    git_date    = s.get("git_last_date", "")
    has_html    = s.get("has_html", False)
    has_pdf     = s.get("has_pdf", False)
    has_pptx    = s.get("has_pptx", False)
    html_path   = s.get("html_path", "")
    best_tok_s  = s.get("best_tok_s") or 0
    gen_count   = s.get("gen_count", 0)
    last_gen    = s.get("last_generated", "never")

    ink = "rgba(255,255,255,.85)" if color in ("char", "olive") else "rgba(0,0,0,.7)"

    # Top flags
    flag_html = ""
    if pending:
        flag_html = f'<div class="pending-flag">⚠ Pending regen</div>'
    elif dormant > 30:
        flag_html = f'<div class="neglect-flag">◌ Dormant · {dormant}d</div>'
    elif dormant > 7:
        flag_html = f'<div class="neglect-flag">◌ {dormant}d idle</div>'

    # Evo dots
    def _edot(i: int) -> str:
        return '<i class="on"></i>' if i <= evo_level else "<i></i>"
    evo_dots = "".join(_edot(i) for i in range(1, 5))

    # Hero display (large card only)
    if is_display and best_tok_s > 0:
        hero_num  = f"{best_tok_s:.0f}"
        hero_unit = " tok/s"
        hero_sub  = "best generation speed"
    elif is_display:
        hero_num  = str(kpi_slides or gen_count or kpi_files)
        hero_unit = " slides" if kpi_slides else " gens" if gen_count else " files"
        hero_sub  = "total across all runs" if kpi_slides else "since project start"

    display_block = ""
    if is_display:
        display_block = (
            f'<div class="display-num">'
            f'<span class="car">^</span>{hero_num}'
            f'<span style="font-size:70px;vertical-align:8px">{hero_unit}</span>'
            f'</div>'
            f'<div class="display-sub">{hero_sub}</div>'
        )

    # Output badges
    badges = "".join(
        f'<span class="badge-fmt{" dim" if not ok else ""}">{fmt}</span>'
        for fmt, ok in [("HTML", has_html), ("PDF", has_pdf), ("PPTX", has_pptx)]
    )

    # Tags row
    tags_html = ""
    if tags:
        tag_pills = "".join(f'<span class="proj-tag">{t}</span>' for t in tags[:5])
        tags_html = f'<div class="proj-tags">{tag_pills}</div>'

    # Status badge
    status_colors = {"active": "var(--ember)", "planning": "var(--dusk)", "paused": "rgba(20,20,20,.4)", "shipped": "#4caf50"}
    status_color = status_colors.get(status, "var(--ember)")
    status_badge = (
        f'<span style="font-family:var(--mono);font-size:9px;letter-spacing:.12em;'
        f'text-transform:uppercase;opacity:.7;border:1px solid {status_color};'
        f'padding:2px 7px;border-radius:999px;color:{status_color}">{status}</span>'
    )

    # Git pulse
    git_html = ""
    if git_branch:
        git_html = (
            f'<div class="git-pulse">'
            f'<span class="branch">{git_branch}</span>'
            f'<span>{git_commits} commits</span>'
            f'<span class="commit-msg">"{git_msg[:40]}"</span>'
            f'<span style="margin-left:auto;opacity:.55">{git_date}</span>'
            f'</div>'
        )

    name_display = f'<em>{name.split("-")[1]}</em>' if "-" in name else f'<em>{name}</em>'
    card_name_html = name.replace("-", "-<em>", 1).replace("<em>", "<em>", 1) if "-" in name else name
    # Simpler: just show the name with the last part italicized
    parts = name.split("-")
    if len(parts) >= 2:
        card_name_html = "-".join(parts[:-1]) + "-<em>" + parts[-1] + "</em>"
    else:
        card_name_html = name

    open_btn = (f'<button class="btn-primary" onclick="openDetail(\'{path}\')">Open deck</button>'
                if has_html else
                f'<button class="btn-primary" onclick="openDetail(\'{path}\')">Details</button>')

    run_cmd = f"sarathi make {Path(path).name}/ --once"

    return f"""<article class="card {layout} {color}" data-domain="{s.get('domain','auto')}" data-path="{path}">
  <div class="card-evo"><span class="evo-dots">{evo_dots}</span> {evo_label}</div>
  <div class="card-domain">{domain}</div>
  {flag_html}

  {"" if is_display else f'<h2 class="card-title">{card_name_html}</h2><p class="card-desc">{desc[:100]}</p>'}
  {"" if is_display else f'<div style="display:flex;align-items:center;gap:8px;margin-top:4px">{status_badge}{tags_html}</div>'}
  {display_block}
  {"" if not is_display else f'<h2 class="card-title" style="font-size:26px;margin-top:22px">{card_name_html}</h2>'}

  <div class="kpi-row">
    <div class="kpi"><div class="kpi-n">{kpi_files}</div><div class="kpi-l">Files</div></div>
    <div class="kpi"><div class="kpi-n">{kpi_slides or "—"}</div><div class="kpi-l">Slides</div></div>
    <div class="kpi"><div class="kpi-n">{kpi_ms}</div><div class="kpi-l">Milestones</div></div>
    <div class="kpi"><div class="kpi-n">{age}</div><div class="kpi-l">Age</div></div>
  </div>

  {_render_spark(spark, ink)}

  <p class="narrative">{narrative}</p>
  {git_html}

  <div class="card-actions">
    {open_btn}
    <button class="btn-ghost" onclick="openDetail('{path}')">Details</button>
    <div class="badges" style="margin-left:auto;margin-top:0">{badges}</div>
  </div>
  <div class="run-cmd">
    <span>$ {run_cmd}</span>
    <span class="cp" onclick="copyCmd(this, '{run_cmd}')">copy</span>
  </div>
</article>"""


def _versions_panel_html(project_dir: Path) -> str:
    from . import tracker as trk
    versions = trk.get_versions(project_dir)
    if not versions:
        return ""

    rows = []
    for v in reversed(versions):
        n        = v.get("version", "?")
        ms       = v.get("milestone", "—")
        ts       = v.get("ts", "")[:10]
        slides   = v.get("slide_count", 0)
        model    = v.get("model", "—")
        dur      = v.get("duration_s", 0)
        html_p   = v.get("html_path", "")
        open_btn = (f'<a href="/open?path={html_p}" target="_blank" '
                    f'style="font-family:var(--mono);font-size:10px;color:var(--ember);'
                    f'text-decoration:none">open ↗</a>'
                    if html_p and Path(html_p).exists() else "—")
        rows.append(
            f'<tr>'
            f'<td style="font-family:var(--serif);font-size:18px;font-weight:500">v{n}</td>'
            f'<td style="font-family:var(--serif);font-style:italic;font-size:15px">{ms}</td>'
            f'<td style="font-family:var(--mono);font-size:11px;opacity:.6">{ts}</td>'
            f'<td style="font-family:var(--mono);font-size:11px">{slides or "—"} slides</td>'
            f'<td style="font-family:var(--mono);font-size:11px;opacity:.7">{model}</td>'
            f'<td style="font-family:var(--mono);font-size:11px;opacity:.6">{dur:.0f}s</td>'
            f'<td>{open_btn}</td>'
            f'</tr>'
        )

    return f"""<section class="panel span-12">
  <div class="section-h">
    <h3>Version <em>history</em></h3>
    <div class="meta">{len(versions)} snapshot{"s" if len(versions) != 1 else ""} · milestone-anchored</div>
  </div>
  <table style="width:100%;border-collapse:collapse">
    <thead><tr style="border-bottom:1px solid var(--line)">
      <th style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;padding:6px 8px;text-align:left">Ver</th>
      <th style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;padding:6px 8px;text-align:left">Milestone</th>
      <th style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;padding:6px 8px;text-align:left">Date</th>
      <th style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;padding:6px 8px;text-align:left">Slides</th>
      <th style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;padding:6px 8px;text-align:left">Model</th>
      <th style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;padding:6px 8px;text-align:left">Duration</th>
      <th style="font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;padding:6px 8px;text-align:left">Open</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  <p style="font-family:var(--mono);font-size:10px;opacity:.45;margin-top:14px">
    Versions are snapshotted automatically when you run <code>sarathi mark</code>.
    Latest is always at <code>output/presentation.html</code>.
  </p>
</section>"""


def _detail_page_html(s: dict, git: dict, files: dict, css: str) -> str:
    name        = s.get("name", "Unnamed")
    desc        = s.get("description", "") or ""
    goal        = s.get("goal", "") or ""
    tags        = s.get("tags") or []
    status      = s.get("status", "active")
    repo_url    = s.get("repo_url", "") or ""
    notes_url   = s.get("notes_url", "") or ""
    team        = s.get("team", "solo") or "solo"
    domain      = s.get("domain", "auto").upper()
    evo_level   = s.get("evo_level", 1)
    evo_label   = s.get("evo_label", "Seed")
    path        = s.get("path", "")
    gen_events  = s.get("gen_events", [])
    milestones  = s.get("milestones_full", [])
    timeline    = s.get("timeline", [])
    tl_days     = s.get("timeline_days", {})
    has_html    = s.get("has_html", False)
    html_path   = s.get("html_path", "")
    planner     = s.get("planner_model", "—")
    coder       = s.get("coder_model", "—")
    vision      = s.get("vision_model", "—")
    fast_m      = s.get("fast_model", "—")
    commits     = git.get("commits", [])
    top_files   = git.get("top_files", [])
    weekly_spark= git.get("weekly_spark", [])
    total_commits = git.get("total_commits", "?")
    git_branch  = git.get("branch", "—")
    gen_count   = s.get("gen_count", 0)
    kpi_files   = sum(s.get("file_types", {}).values())
    age         = s.get("project_age", "—")
    fastest_s   = s.get("fastest_s")
    best_tok_s  = s.get("best_tok_s")
    largest     = s.get("largest_slides")

    def _ed(i: int) -> str:
        return '<i class="on"></i>' if i <= evo_level else "<i></i>"
    evo_dots = "".join(_ed(i) for i in range(1, 5))

    parts = name.split("-")
    hero_name = (("-".join(parts[:-1]) + "-<em>" + parts[-1] + "</em>") if len(parts) >= 2 else name)

    # Stat tiles
    def tile(cls, label, num, foot=""):
        foot_html = f'<div class="st-foot">{foot}</div>' if foot else ""
        return (f'<div class="stat-tile {cls}">'
                f'<div class="st-l">{label}</div>'
                f'<div class="st-n">{num}</div>'
                f'{foot_html}'
                f'</div>')

    stat_tiles = (
        tile("accent",   "Total commits",     f'<span class="car">^</span>{total_commits}', f'+? this week') +
        tile("accent-2", "Total generations", str(gen_count), f'last gen · {gen_events[-1].get("model","?") if gen_events else "—"}') +
        tile("",         "Total files",       str(kpi_files), " · ".join(f'{v} {k}' for k, v in list(s.get("file_types", {}).items())[:3])) +
        tile("accent-3", "Age",               age,            f'started {s.get("created","?")} · last active today') +
        tile("",         "Fastest generation",f'{fastest_s:.0f}s' if fastest_s else "—", "") +
        tile("",         "Best tok/s",        f'<span class="car">^</span>{best_tok_s:.0f}' if best_tok_s else "—", "")
    )

    # Commit rows
    commit_rows = "".join(
        f'<tr><td class="hash">{c["hash"]}</td>'
        f'<td class="msg">{c["msg"]}</td>'
        f'<td>{c["date"]}</td>'
        f'<td class="diff"><span class="plus">+{c["added"]}</span> / <span class="minus">−{c["deleted"]}</span></td>'
        f'</tr>'
        for c in commits[:10]
    )

    # Commit weekly sparkline SVG
    commit_spark_svg = ""
    if weekly_spark:
        mx = max(weekly_spark, default=1) or 1
        pts = [(i * 400/max(len(weekly_spark)-1,1), 50 - (v/mx)*44) for i, v in enumerate(weekly_spark)]
        path_d = " ".join(("M" if i==0 else "L") + f"{x:.1f},{y:.1f}" for i,(x,y) in enumerate(pts))
        commit_spark_svg = (
            f'<svg class="commit-spark" viewBox="0 0 400 50" preserveAspectRatio="none" style="color:var(--ink)">'
            f'<path class="line" d="{path_d}"/></svg>'
        )

    # Model cards
    def mcard(role, cls, model_name, tps=None):
        tps_html = f'<div class="toks"><span class="car">^</span>{tps:.0f} <span style="font-size:12px;opacity:.6">tok/s</span></div>' if tps else ""
        return (f'<div class="model-card {cls}">'
                f'<div class="role">— {role}</div>'
                f'<div class="name">{model_name}</div>'
                f'{tps_html}'
                f'</div>')

    # Extract best tok/s per role model from events
    role_tps: dict[str, float] = {}
    for e in gen_events:
        m = e.get("model", "")
        t = e.get("tok_s", 0)
        if m and t and t > role_tps.get(m, 0):
            role_tps[m] = t

    model_cards = (
        mcard("Planner", "planner", planner, role_tps.get(planner)) +
        mcard("Coder",   "coder",   coder,   role_tps.get(coder)) +
        mcard("Vision",  "vision",  vision,  role_tps.get(vision)) +
        mcard("Fast",    "fast",    fast_m,  role_tps.get(fast_m))
    )

    open_btn = (f'<a class="btn-primary" href="/open?path={html_path}" target="_blank">Open presentation</a>'
                if has_html else "")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{name} — Sarathi</title>
<meta name="viewport" content="width=1440"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,400;1,6..72,500&family=Bricolage+Grotesque:opsz,wght@12..96,300;12..96,400;12..96,500;12..96,600;12..96,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="frame"><div class="stage">

<header class="topbar">
  <div class="brand">
    <div class="brand-mark">s</div>
    <div>
      <div class="brand-name">Sarathi<span class="ast">*</span></div>
      <div class="brand-sub">{name} · single project</div>
    </div>
  </div>
  <div class="status-row" id="status-row-detail">
    <span class="pill"><span class="dot" id="ollama-dot-d"></span> Ollama <code id="ollama-model-d">—</code></span>
  </div>
  <div class="global-stats">
    <div class="gs-cell"><div class="gs-num">{kpi_files}</div><div class="gs-lbl">Files</div></div>
    <div class="gs-cell"><div class="gs-num">{s.get("slide_count","—")}</div><div class="gs-lbl">Slides</div></div>
    <div class="gs-cell"><div class="gs-num">{len(s.get("milestones",[]))}</div><div class="gs-lbl">Milestones</div></div>
  </div>
</header>

<div class="detail-backbar">
  <a class="back-link" href="/">Back to portfolio</a>
  <div>{name} · {domain} · <span class="ast">{'★' if evo_level==4 else '·'}</span> {evo_label}</div>
</div>

<section class="hero">
  <div class="hero-top">
    <div>
      <div class="hero-meta">
        <span>Domain: {domain}</span>
        <span class="evo-dots">{evo_dots}</span>
        <span>{evo_label}</span>
        <span style="text-transform:none;letter-spacing:0;font-style:italic;opacity:.7">{status}</span>
        {"<span>· " + team + "</span>" if team and team != "solo" else ""}
      </div>
      <h1 class="hero-title">{hero_name}</h1>
      <p class="hero-desc">{desc}</p>
      {"<p style='font-family:var(--sans);font-size:15px;line-height:1.5;max-width:70ch;margin-top:10px;color:var(--ink-2)'>" + goal + "</p>" if goal else ""}
      {"<div style='display:flex;flex-wrap:wrap;gap:6px;margin-top:10px'>" + "".join(f'<span style="font-family:var(--mono);font-size:10px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);background:var(--off-white)">{t}</span>' for t in tags) + "</div>" if tags else ""}
      {"<div style='margin-top:12px;font-family:var(--mono);font-size:11px;display:flex;gap:18px'>" + (f'<a href="{repo_url}" target="_blank" style="color:var(--ember)">⎇ repository ↗</a>' if repo_url else "") + (f'<a href="{notes_url}" target="_blank" style="color:var(--dusk)">⇗ related link</a>' if notes_url else "") + "</div>" if (repo_url or notes_url) else ""}
    </div>
    <div class="hero-actions">
      {open_btn}
      <button class="btn-ghost" onclick="history.back()">← Back</button>
    </div>
  </div>
  <div class="hero-stats">{stat_tiles}</div>
</section>

<div class="panels">

  <section class="panel dark span-8">
    <div class="section-h"><h3>One year of activity <span class="ast">,</span></h3><div class="meta">52 weeks · 7 days</div></div>
    {_heatmap_html(tl_days)}
    <div class="heat-axis"><span>52w ago</span><span>39w</span><span>26w</span><span>13w</span><span>Now</span></div>
    <div class="heat-legend">
      less
      <span class="lg" style="background:rgba(255,255,255,.06)"></span>
      <span class="lg" style="background:rgba(244,210,74,.22)"></span>
      <span class="lg" style="background:rgba(244,210,74,.45)"></span>
      <span class="lg" style="background:rgba(244,210,74,.7)"></span>
      <span class="lg" style="background:var(--mustard)"></span>
      more
    </div>
  </section>

  <section class="panel accent span-4">
    <div class="section-h"><h3>Personal <em>bests</em></h3><div class="meta">all-time</div></div>
    <div style="font-family:var(--serif);font-size:64px;line-height:.9;margin:8px 0 4px">
      {'<span style="color:var(--ember);font-size:26px;vertical-align:22px">^</span>' + f'{best_tok_s:.0f}' if best_tok_s else '—'}
      <span style="font-size:22px;opacity:.6">tok/s</span>
    </div>
    <div style="margin-top:18px;padding-top:14px;border-top:1px solid rgba(0,0,0,.15);font-family:var(--mono);font-size:11px">
      <div style="display:flex;justify-content:space-between;padding:6px 0"><span style="opacity:.6">Fastest gen</span><span>{f"{fastest_s:.0f}s" if fastest_s else "—"}</span></div>
      <div style="display:flex;justify-content:space-between;padding:6px 0"><span style="opacity:.6">Largest deck</span><span>{f"{largest} slides" if largest else "—"}</span></div>
      <div style="display:flex;justify-content:space-between;padding:6px 0"><span style="opacity:.6">Total gens</span><span>{gen_count}</span></div>
      <div style="display:flex;justify-content:space-between;padding:6px 0"><span style="opacity:.6">Branch</span><span>{git_branch}</span></div>
    </div>
  </section>

  <section class="panel span-7">
    <div class="section-h"><h3>What happened, <em>recently</em></h3><div class="meta">narrative feed</div></div>
    <div class="feed">{_feed_html(timeline)}</div>
  </section>

  <section class="panel dark span-5">
    <div class="section-h"><h3>Generation <em>history</em></h3><div class="meta">last {min(10,len(gen_events))} runs</div></div>
    {_gen_table_html(gen_events)}
    <div style="margin-top:22px">
      <div class="panel-sub" style="margin-bottom:12px">Model speed · tok/s by role</div>
      {_model_chart_html(gen_events)}
    </div>
  </section>

  <section class="panel span-7">
    <div class="section-h"><h3>Git <em>pulse</em></h3><div class="meta">branch: {git_branch} · {total_commits} commits</div></div>
    <table class="commits"><thead><tr><th>Hash</th><th>Message</th><th>Date</th><th>Δ</th></tr></thead>
    <tbody>{commit_rows}</tbody></table>
    <div style="margin-top:22px">
      <div class="panel-sub" style="margin-bottom:8px">Top 5 most-changed files</div>
      {_filebar_html(top_files)}
    </div>
    <div style="margin-top:22px">
      <div class="panel-sub" style="margin-bottom:8px">Commit frequency · weekly</div>
      {commit_spark_svg}
    </div>
  </section>

  <section class="panel span-5">
    <div class="section-h"><h3>Files <em>browser</em></h3><div class="meta">{kpi_files} in tree</div></div>
    {_file_browser_html(files)}
  </section>

  <section class="panel span-7">
    <div class="section-h"><h3>Data <em>insights</em></h3><div class="meta">auto-profiled CSVs</div></div>
    {_data_insights_html(files, Path(path))}
  </section>

  <section class="panel span-5">
    <div class="section-h"><h3>Milestones <em>,</em> in order</h3><div class="meta">{len(milestones)} marked</div></div>
    {_milestone_timeline_html(milestones)}
  </section>

  <section class="panel span-12">
    <div class="section-h"><h3>Models <em>in rotation</em></h3><div class="meta">4 roles · auto-routed</div></div>
    <div class="model-cards">{model_cards}</div>
  </section>

  {_versions_panel_html(Path(path))}

</div>
</div></div>

<script>
async function pollStatus() {{
  try {{
    const r = await fetch('/api/status');
    const d = await r.json();
    const dot   = document.getElementById('ollama-dot-d');
    const label = document.getElementById('ollama-model-d');
    if (dot && label) {{
      dot.style.background = d.ollama?.running ? '#4caf50' : '#f06060';
      label.textContent = d.ollama?.loaded_model || (d.ollama?.running ? 'idle' : 'offline');
    }}
  }} catch(e) {{}}
}}
pollStatus();
setInterval(pollStatus, 8000);
</script>
</body></html>"""


# ── CSS (from design file, adapted for Flask injection) ──────────────────────

_CSS = """
:root {
  --ink:       #141414;
  --ink-2:     #2a2a2a;
  --paper:     #ECE6D6;
  --paper-2:   #DFD8C7;
  --line:      rgba(20,20,20,.14);
  --mustard:   #F4D24A;
  --ember:     #EA4A1F;
  --dusk:      #8B82A5;
  --olive:     #6E6C1E;
  --char:      #171717;
  --mint:      #BCE5B0;
  --candy:     #F2A8D8;
  --sky:       #A8D6E0;
  --off-white: #F4EFE3;
  --lilac:     #C8C3DE;
  --serif: 'Newsreader', 'Times New Roman', serif;
  --sans:  'Bricolage Grotesque', system-ui, sans-serif;
  --mono:  'JetBrains Mono', ui-monospace, monospace;
}
* { box-sizing: border-box; }
html, body { margin:0; padding:0; }
body { font-family:var(--sans); background:#0d0d0d; color:var(--ink); font-size:14px; line-height:1.4; -webkit-font-smoothing:antialiased; }
::selection { background:var(--mustard); color:var(--ink); }
a { color:inherit; text-decoration:none; }
.frame { min-height:100vh; padding:18px 18px 28px; background:#0d0d0d; }
.stage { max-width:1400px; margin:0 auto; background:var(--paper); border-radius:6px; overflow:hidden; }
.ast { color:var(--ember); font-family:var(--serif); font-style:italic; }

/* TOP BAR */
.topbar { display:grid; grid-template-columns:220px 1fr auto; align-items:center; gap:24px; padding:16px 22px; border-bottom:1px solid var(--line); background:var(--paper); }
.brand { display:flex; align-items:center; gap:10px; }
.brand-mark { width:30px; height:30px; background:var(--ink); border-radius:50%; display:grid; place-items:center; color:var(--paper); font-family:var(--serif); font-size:20px; font-style:italic; }
.brand-name { font-family:var(--serif); font-size:26px; line-height:1; letter-spacing:-.01em; }
.brand-name em { font-style:italic; color:var(--ember); }
.brand-sub { font-family:var(--mono); font-size:10px; text-transform:uppercase; letter-spacing:.14em; color:rgba(20,20,20,.55); margin-top:2px; }
.status-row { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.pill { display:inline-flex; align-items:center; gap:8px; padding:7px 12px; border:1px solid var(--line); border-radius:999px; background:rgba(255,255,255,.4); font-size:12px; font-weight:500; white-space:nowrap; }
.pill .dot { width:7px; height:7px; border-radius:50%; background:#4caf50; box-shadow:0 0 0 3px rgba(76,175,80,.18); }
.pill .dot.warn { background:#e8a020; box-shadow:0 0 0 3px rgba(232,160,32,.18); }
.pill .dot.gen  { background:var(--ember); animation:pulse 1.4s infinite ease-in-out; }
@keyframes pulse { 0%,100%{transform:scale(1);opacity:1} 50%{transform:scale(.7);opacity:.5} }
.pill code { font-family:var(--mono); font-size:11px; background:var(--ink); color:var(--paper); padding:2px 6px; border-radius:3px; }
.pill .meta { color:rgba(20,20,20,.5); font-family:var(--mono); font-size:11px; }
.global-stats { display:flex; align-items:stretch; border:1px solid var(--line); border-radius:4px; overflow:hidden; background:rgba(255,255,255,.35); }
.gs-cell { padding:6px 14px; border-right:1px solid var(--line); text-align:left; }
.gs-cell:last-child { border-right:0; }
.gs-cell .gs-num { font-family:var(--serif); font-size:22px; line-height:1; }
.gs-cell .gs-lbl { font-family:var(--mono); font-size:9px; text-transform:uppercase; letter-spacing:.12em; color:rgba(20,20,20,.55); margin-top:3px; }

/* INSIGHT BANNER */
.insight { display:grid; grid-template-columns:auto 1fr auto auto; gap:18px; align-items:center; padding:14px 22px; background:var(--char); color:var(--paper); }
.insight-tag { font-family:var(--mono); font-size:10px; letter-spacing:.18em; text-transform:uppercase; color:var(--mustard); padding-right:18px; border-right:1px solid rgba(255,255,255,.15); }
.insight-text { font-family:var(--serif); font-size:20px; line-height:1.15; letter-spacing:-.005em; }
.insight-text .ember { color:var(--ember); font-style:italic; }
.insight-text code { font-family:var(--mono); font-size:13px; background:rgba(255,255,255,.1); padding:2px 6px; border-radius:3px; color:var(--mint); }
.insight-text em { font-style:italic; color:var(--mustard); }
.insight-time { font-family:var(--mono); font-size:11px; color:rgba(255,255,255,.5); }
.insight-close { background:transparent; border:1px solid rgba(255,255,255,.25); color:var(--paper); width:26px; height:26px; border-radius:50%; cursor:pointer; font-size:14px; }
.insight-close:hover { background:rgba(255,255,255,.08); }

/* TOOLBAR */
.toolbar { display:grid; grid-template-columns:1fr auto auto; gap:14px; align-items:center; padding:14px 22px; background:var(--paper); border-bottom:1px solid var(--line); }
.search { display:flex; align-items:center; gap:10px; padding:8px 14px; border:1px solid var(--line); border-radius:999px; background:var(--off-white); }
.search input { flex:1; border:0; background:transparent; outline:none; font-family:var(--sans); font-size:14px; }
.search .kbd { font-family:var(--mono); font-size:10px; border:1px solid var(--line); border-radius:3px; padding:1px 6px; color:rgba(20,20,20,.55); }
.filter-chips { display:flex; gap:6px; }
.chip { font-family:var(--mono); font-size:11px; padding:7px 12px; border:1px solid var(--line); border-radius:999px; background:transparent; cursor:pointer; text-transform:lowercase; letter-spacing:.02em; }
.chip.active { background:var(--ink); color:var(--paper); border-color:var(--ink); }
.sort-btn { font-family:var(--mono); font-size:11px; padding:7px 12px; border:1px solid var(--line); border-radius:999px; background:transparent; cursor:pointer; display:inline-flex; gap:6px; align-items:center; }
.sort-btn::after { content:"↓"; font-size:12px; }

/* WRAPPED */
.wrapped { display:grid; grid-template-columns:auto 1fr auto; gap:20px; align-items:center; margin:22px 22px 0; padding:14px 18px; background:var(--off-white); border:1px solid var(--line); border-radius:4px; }
.wrapped-label { font-family:var(--serif); font-style:italic; font-size:22px; line-height:1; padding-right:16px; border-right:1px solid var(--line); }
.wrapped-stats { display:flex; gap:32px; }
.ws { display:flex; flex-direction:column; gap:2px; }
.ws-num { font-family:var(--serif); font-size:24px; line-height:1; }
.ws-num .car { color:var(--ember); font-size:14px; vertical-align:4px; }
.ws-lbl { font-family:var(--mono); font-size:9px; letter-spacing:.12em; text-transform:uppercase; color:rgba(20,20,20,.55); }
.wrapped-close { background:transparent; border:1px solid var(--line); width:28px; height:28px; border-radius:50%; cursor:pointer; }

/* BENTO GRID */
.bento { display:grid; grid-template-columns:repeat(12, 1fr); gap:10px; padding:22px; }
.card { border-radius:4px; padding:22px 22px 18px; position:relative; overflow:hidden; display:flex; flex-direction:column; min-height:260px; }
.card.large  { grid-column:span 4; min-height:320px; }
.card.medium { grid-column:span 4; }
.card.small  { grid-column:span 3; }
.card.wide   { grid-column:span 6; }
.card.tall   { grid-column:span 4; min-height:360px; }
.card.display { justify-content:flex-start; }
.card.mustard { background:var(--mustard); color:var(--ink); }
.card.ember   { background:var(--ember);   color:var(--ink); }
.card.dusk    { background:var(--dusk);    color:var(--ink); }
.card.olive   { background:var(--olive);   color:var(--off-white); }
.card.char    { background:var(--char);    color:var(--paper); }
.card.cream   { background:var(--off-white); color:var(--ink); }
.card.mint    { background:var(--mint);    color:var(--ink); }
.card.candy   { background:var(--candy);   color:var(--ink); }
.card.sky     { background:var(--sky);     color:var(--ink); }
.card.lilac   { background:var(--lilac);   color:var(--ink); }
.card-domain { position:absolute; top:18px; right:18px; font-family:var(--mono); font-size:10px; letter-spacing:.14em; text-transform:uppercase; opacity:.55; }
.card-evo { position:absolute; top:18px; left:18px; font-family:var(--mono); font-size:10px; letter-spacing:.14em; text-transform:uppercase; display:inline-flex; gap:6px; align-items:center; }
.evo-dots { display:inline-flex; gap:3px; }
.evo-dots i { width:5px; height:5px; border-radius:50%; background:currentColor; opacity:.25; display:inline-block; }
.evo-dots i.on { opacity:1; }
.card-title { font-family:var(--serif); font-size:40px; line-height:1; letter-spacing:-.01em; margin:56px 0 6px; }
.card.large .card-title { font-size:52px; }
.card-title em { font-style:italic; }
.card-desc { font-size:12.5px; line-height:1.4; max-width:36ch; opacity:.8; }
.kpi-row { display:grid; grid-template-columns:repeat(4, 1fr); gap:4px; margin-top:auto; padding-top:18px; }
.kpi { display:flex; flex-direction:column; gap:1px; }
.kpi-n { font-family:var(--serif); font-size:22px; line-height:1; }
.kpi-l { font-family:var(--mono); font-size:9px; letter-spacing:.1em; text-transform:uppercase; opacity:.55; }
.spark { height:28px; width:100%; margin:10px 0 8px; display:block; }
.spark .line { fill:none; stroke:currentColor; stroke-width:1.5; }
.spark .area { fill:currentColor; opacity:.14; }
.spark .dot  { fill:currentColor; }
.narrative { font-family:var(--serif); font-style:italic; font-size:15px; line-height:1.3; margin:8px 0 0; max-width:38ch; }
.git-pulse { display:flex; gap:12px; align-items:center; font-family:var(--mono); font-size:11px; padding-top:10px; margin-top:10px; border-top:1px dashed currentColor; opacity:.85; }
.git-pulse .branch::before { content:""; display:inline-block; width:6px; height:6px; border-radius:50%; background:currentColor; margin-right:6px; vertical-align:1px; }
.git-pulse .commit-msg { font-family:var(--sans); font-style:italic; opacity:.75; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:24ch; }
.badges { display:flex; gap:4px; margin-top:10px; }
.badge-fmt { font-family:var(--mono); font-size:9px; letter-spacing:.1em; padding:3px 7px; border:1px solid currentColor; border-radius:3px; text-transform:uppercase; opacity:.85; }
.badge-fmt.dim { opacity:.25; text-decoration:line-through; }
.pending-flag { position:absolute; top:14px; left:50%; transform:translateX(-50%); font-family:var(--mono); font-size:9px; letter-spacing:.14em; text-transform:uppercase; background:var(--ember); color:var(--off-white); padding:3px 10px; border-radius:999px; }
.neglect-flag { position:absolute; top:14px; left:50%; transform:translateX(-50%); font-family:var(--mono); font-size:9px; letter-spacing:.14em; text-transform:uppercase; background:rgba(0,0,0,.65); color:#fff; padding:3px 10px; border-radius:999px; }
.card-actions { display:flex; gap:8px; margin-top:12px; align-items:center; }
.btn-primary { font-family:var(--sans); font-size:12px; font-weight:500; padding:8px 14px; border-radius:999px; border:1px solid currentColor; background:var(--ink); color:var(--paper); cursor:pointer; display:inline-flex; gap:8px; align-items:center; }
.btn-primary::after { content:"↗"; font-size:13px; }
.card.char .btn-primary { background:var(--paper); color:var(--ink); border-color:var(--paper); }
.btn-ghost { font-family:var(--sans); font-size:12px; padding:8px 12px; border-radius:999px; border:1px solid currentColor; background:transparent; color:inherit; cursor:pointer; opacity:.85; }
.run-cmd { margin-top:10px; font-family:var(--mono); font-size:11px; padding:8px 12px; background:rgba(0,0,0,.12); border-radius:4px; display:flex; justify-content:space-between; align-items:center; gap:10px; }
.card.char .run-cmd { background:rgba(255,255,255,.06); }
.card.ember .run-cmd { background:rgba(0,0,0,.18); }
.run-cmd .cp { font-family:var(--mono); font-size:9px; letter-spacing:.1em; opacity:.6; cursor:pointer; text-transform:uppercase; }
.display-num { font-family:var(--serif); font-size:130px; line-height:.9; letter-spacing:-.025em; margin:38px 0 0; }
.display-num .car { font-size:36px; vertical-align:38px; margin-right:4px; }
.display-sub { font-size:13px; max-width:22ch; margin:14px 0 0; }
.card-foot { margin-top:auto; padding-top:14px; border-top:1px solid rgba(0,0,0,.18); display:flex; justify-content:space-between; align-items:center; font-family:var(--mono); font-size:10px; letter-spacing:.1em; text-transform:uppercase; opacity:.75; }
.card.char .card-foot, .card.olive .card-foot { border-color:rgba(255,255,255,.18); }

/* PERSONALITY */
.personality { display:grid; grid-template-columns:2fr 1.2fr; gap:10px; padding:0 22px 22px; }
.achievements { background:var(--paper); border:1px solid var(--line); border-radius:4px; padding:22px; }
.section-h { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:16px; }
.section-h h3 { font-family:var(--serif); font-size:24px; margin:0; font-style:italic; }
.section-h .meta { font-family:var(--mono); font-size:10px; letter-spacing:.14em; text-transform:uppercase; color:rgba(20,20,20,.55); }
.badge-grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; }
.ach { border:1px solid var(--line); border-radius:4px; padding:14px; background:var(--off-white); display:flex; flex-direction:column; gap:6px; position:relative; min-height:102px; }
.ach.locked { opacity:.42; background:transparent; }
.ach-glyph { width:28px; height:28px; border-radius:50%; background:var(--ink); color:var(--paper); display:grid; place-items:center; font-family:var(--serif); font-size:16px; font-style:italic; }
.ach.unlocked .ach-glyph { background:var(--ember); color:var(--ink); }
.ach-name { font-weight:500; font-size:12.5px; }
.ach-desc { font-family:var(--mono); font-size:10px; opacity:.65; line-height:1.35; }
.ach.unlocked::after { content:"UNLOCKED"; position:absolute; top:10px; right:12px; font-family:var(--mono); font-size:8px; letter-spacing:.14em; color:var(--ember); }
.ach.locked::after { content:"🔒"; position:absolute; top:10px; right:12px; opacity:.4; font-size:11px; }
.quote { background:var(--ink); color:var(--paper); border-radius:4px; padding:28px 28px 22px; display:flex; flex-direction:column; justify-content:space-between; }
.quote-mark { font-family:var(--serif); font-size:110px; line-height:.8; color:var(--mustard); margin-bottom:-10px; }
.quote-body { font-family:var(--serif); font-size:24px; line-height:1.2; letter-spacing:-.005em; }
.quote-body em { font-style:italic; color:var(--mustard); }
.quote-attr { font-family:var(--mono); font-size:11px; letter-spacing:.1em; margin-top:18px; padding-top:14px; border-top:1px solid rgba(255,255,255,.15); color:rgba(255,255,255,.65); text-transform:uppercase; }

/* KBD BAR */
.kbd-bar { display:flex; gap:18px; flex-wrap:wrap; padding:16px 22px 24px; border-top:1px solid var(--line); background:var(--paper); font-family:var(--mono); font-size:11px; color:rgba(20,20,20,.6); }
.kbd-bar .pair { display:inline-flex; gap:8px; align-items:center; }
.k { display:inline-block; border:1px solid var(--line); border-bottom-width:2px; border-radius:3px; padding:1px 6px; font-size:10px; background:var(--off-white); color:var(--ink); }
.float-help { position:fixed; right:28px; bottom:22px; background:var(--char); color:var(--paper); padding:8px 12px; border-radius:999px; font-family:var(--mono); font-size:11px; box-shadow:0 8px 24px rgba(0,0,0,.3); display:flex; gap:10px; align-items:center; z-index:5; cursor:pointer; border:none; }
.float-help .k { background:rgba(255,255,255,.12); color:var(--paper); border-color:rgba(255,255,255,.2); }
.card.hidden { display:none; }

/* DETAIL VIEW */
.detail-backbar { padding:12px 22px; border-bottom:1px solid var(--line); background:var(--paper); display:flex; justify-content:space-between; align-items:center; font-family:var(--mono); font-size:11px; letter-spacing:.12em; text-transform:uppercase; }
.back-link { font:inherit; letter-spacing:inherit; text-transform:inherit; cursor:pointer; color:var(--ink); display:inline-flex; align-items:center; gap:8px; }
.back-link::before { content:"←"; font-size:14px; }
.hero { padding:28px 22px 22px; background:var(--paper); }
.hero-top { display:grid; grid-template-columns:1fr auto; gap:28px; align-items:end; padding-bottom:22px; border-bottom:1px solid var(--line); margin-bottom:18px; }
.hero-title { font-family:var(--serif); font-size:96px; line-height:.92; letter-spacing:-.02em; margin:6px 0 0; }
.hero-title em { font-style:italic; color:var(--ember); }
.hero-meta { display:flex; gap:18px; align-items:center; font-family:var(--mono); font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:rgba(20,20,20,.6); }
.hero-desc { font-family:var(--serif); font-size:20px; font-style:italic; max-width:60ch; line-height:1.3; margin-top:8px; color:var(--ink-2); }
.hero-actions { display:flex; gap:8px; }
.hero-stats { display:grid; grid-template-columns:repeat(6, 1fr); gap:10px; }
.stat-tile { background:var(--off-white); border:1px solid var(--line); border-radius:4px; padding:18px; display:flex; flex-direction:column; min-height:112px; }
.stat-tile.accent { background:var(--mustard); border-color:var(--mustard); }
.stat-tile.accent-2 { background:var(--ember); border-color:var(--ember); }
.stat-tile.accent-3 { background:var(--char); color:var(--paper); border-color:var(--char); }
.stat-tile .st-l { font-family:var(--mono); font-size:10px; letter-spacing:.12em; text-transform:uppercase; opacity:.6; }
.stat-tile .st-n { font-family:var(--serif); font-size:48px; line-height:1; margin-top:auto; }
.stat-tile .st-n .car { color:var(--ember); font-size:22px; vertical-align:16px; margin-right:2px; }
.stat-tile.accent .st-n .car { color:var(--ink); }
.stat-tile .st-foot { font-family:var(--mono); font-size:10px; letter-spacing:.08em; opacity:.55; margin-top:6px; }
.panels { display:grid; grid-template-columns:repeat(12, 1fr); gap:10px; padding:18px 22px 22px; }
.panel { background:var(--off-white); border:1px solid var(--line); border-radius:4px; padding:22px; }
.panel.dark { background:var(--char); color:var(--paper); border-color:var(--char); }
.panel.accent { background:var(--mustard); }
.panel h3 { font-family:var(--serif); font-style:italic; font-size:26px; margin:0 0 4px; }
.panel .panel-sub { font-family:var(--mono); font-size:10px; letter-spacing:.14em; text-transform:uppercase; opacity:.55; margin-bottom:18px; }
.span-12 { grid-column:span 12; }
.span-8  { grid-column:span 8; }
.span-7  { grid-column:span 7; }
.span-6  { grid-column:span 6; }
.span-5  { grid-column:span 5; }
.span-4  { grid-column:span 4; }

/* HEATMAP */
.heatmap { display:grid; grid-template-columns:repeat(52, 1fr); gap:3px; margin-top:8px; }
.heat-col { display:grid; grid-template-rows:repeat(7, 1fr); gap:3px; }
.heat-cell { width:100%; aspect-ratio:1; background:rgba(255,255,255,.06); border-radius:2px; }
.panel.dark .heat-cell.l1 { background:rgba(244,210,74,.22); }
.panel.dark .heat-cell.l2 { background:rgba(244,210,74,.45); }
.panel.dark .heat-cell.l3 { background:rgba(244,210,74,.7); }
.panel.dark .heat-cell.l4 { background:var(--mustard); }
.heat-axis { display:flex; justify-content:space-between; font-family:var(--mono); font-size:10px; letter-spacing:.12em; opacity:.5; margin-top:8px; }
.heat-legend { display:inline-flex; align-items:center; gap:6px; font-family:var(--mono); font-size:10px; opacity:.65; margin-top:8px; }
.heat-legend .lg { width:10px; height:10px; border-radius:2px; }

/* FEED */
.feed { display:flex; flex-direction:column; }
.feed-item { padding:14px 0; border-bottom:1px dashed var(--line); display:grid; grid-template-columns:28px 1fr auto; gap:14px; align-items:baseline; }
.feed-item:last-child { border-bottom:0; }
.feed-glyph { font-family:var(--serif); font-size:18px; line-height:1; color:var(--ember); font-style:italic; }
.feed-item .feed-body { font-family:var(--serif); font-size:16px; line-height:1.3; }
.feed-item .feed-body code { font-family:var(--mono); font-size:12px; background:rgba(0,0,0,.06); padding:1px 5px; border-radius:3px; }
.feed-date { font-family:var(--mono); font-size:10px; letter-spacing:.1em; text-transform:uppercase; opacity:.55; white-space:nowrap; }

/* COMMITS */
.commits { width:100%; border-collapse:collapse; }
.commits th, .commits td { text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); font-size:12.5px; }
.commits th { font-family:var(--mono); font-size:10px; letter-spacing:.12em; text-transform:uppercase; opacity:.55; font-weight:500; }
.commits td.hash { font-family:var(--mono); font-size:11px; }
.commits td.msg { font-style:italic; font-family:var(--serif); font-size:14.5px; }
.commits td.diff .plus { color:#2c7a3e; }
.commits td.diff .minus { color:var(--ember); }

/* FILE BAR */
.filebar { display:flex; flex-direction:column; gap:10px; margin-top:8px; }
.filebar-row { display:grid; grid-template-columns:180px 1fr 36px; gap:12px; align-items:center; font-family:var(--mono); font-size:11px; }
.filebar-row .name { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.filebar-row .bar { height:12px; background:rgba(0,0,0,.06); border-radius:2px; overflow:hidden; }
.filebar-row .bar > div { height:100%; background:var(--ink); }
.filebar-row:nth-child(1) .bar > div { background:var(--ember); }
.filebar-row:nth-child(2) .bar > div { background:var(--mustard); }

/* FILES */
.file-group { margin-bottom:14px; }
.file-group h4 { font-family:var(--mono); font-size:10px; letter-spacing:.14em; text-transform:uppercase; opacity:.55; margin:0 0 8px; }
.file-list { display:flex; flex-direction:column; }
.file-row { display:grid; grid-template-columns:28px 1fr auto auto; gap:12px; padding:8px 0; border-bottom:1px dashed var(--line); font-family:var(--mono); font-size:11.5px; align-items:center; }
.file-row .thumb { width:28px; height:28px; background:linear-gradient(135deg, var(--dusk), var(--candy)); border-radius:3px; color:var(--paper); display:grid; place-items:center; font-family:var(--serif); font-size:12px; font-style:italic; }
.file-row.code .thumb { background:var(--ink); }
.file-row.data .thumb { background:var(--olive); }
.file-row.text .thumb { background:var(--off-white); color:var(--ink); border:1px solid var(--line); }
.file-row .shape { color:rgba(20,20,20,.6); font-size:10.5px; }
.file-row .size { opacity:.55; font-size:10px; letter-spacing:.08em; }

/* DATA CARDS */
.data-cards { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.data-card { border:1px solid var(--line); border-radius:4px; padding:16px; background:var(--paper); }
.data-card h4 { font-family:var(--mono); font-size:11px; margin:0 0 6px; }
.data-card .shape { font-family:var(--serif); font-style:italic; font-size:18px; line-height:1; margin-bottom:12px; }
.data-card .cols { display:flex; flex-wrap:wrap; gap:4px; margin-bottom:12px; }
.data-card .ct { font-family:var(--mono); font-size:10px; padding:2px 7px; border-radius:999px; border:1px solid var(--line); background:var(--off-white); }
.data-card .stats { display:grid; grid-template-columns:1fr 1fr; gap:8px; font-family:var(--mono); font-size:10.5px; }
.data-card .stats .lbl { opacity:.55; }

/* GEN TABLE */
.gen-table { width:100%; border-collapse:collapse; }
.gen-table th, .gen-table td { padding:9px 8px; border-bottom:1px solid rgba(255,255,255,.1); text-align:left; font-size:12.5px; }
.gen-table th { font-family:var(--mono); font-size:10px; letter-spacing:.12em; text-transform:uppercase; opacity:.6; font-weight:500; }
.gen-table td.num { font-family:var(--serif); font-size:16px; }
.gen-table tr.fastest td { background:rgba(244,210,74,.1); }
.gen-table tr.fastest td:first-child { box-shadow:inset 3px 0 0 var(--mustard); }
.gen-table td .tag { font-family:var(--mono); font-size:9px; letter-spacing:.1em; padding:2px 6px; border-radius:2px; background:rgba(255,255,255,.08); }

/* MODEL CHART */
.model-chart { display:flex; flex-direction:column; gap:12px; margin-top:14px; }
.mc-row { display:grid; grid-template-columns:130px 1fr 50px; gap:14px; align-items:center; font-family:var(--mono); font-size:11px; }
.mc-row .name { color:var(--paper); }
.mc-row .role { color:rgba(255,255,255,.5); font-size:10px; }
.mc-row .barwrap { height:14px; background:rgba(255,255,255,.08); border-radius:2px; overflow:hidden; }
.mc-row .barwrap > div { height:100%; background:var(--mustard); }
.mc-row.coder .barwrap > div { background:var(--ember); }
.mc-row.fast  .barwrap > div { background:var(--mint); }
.mc-row.vision .barwrap > div { background:var(--candy); }
.mc-row .val { font-family:var(--serif); font-size:18px; color:var(--paper); text-align:right; }

/* MILESTONES */
.timeline { position:relative; padding-left:18px; }
.timeline::before { content:""; position:absolute; left:6px; top:6px; bottom:6px; border-left:1px dashed var(--line); }
.ms { position:relative; padding:12px 0 14px; border-bottom:1px dashed var(--line); }
.ms:last-child { border-bottom:0; }
.ms::before { content:""; position:absolute; left:-18px; top:18px; width:12px; height:12px; border-radius:50%; background:var(--ember); border:3px solid var(--off-white); }
.ms .ms-date { font-family:var(--mono); font-size:10px; letter-spacing:.12em; text-transform:uppercase; opacity:.55; }
.ms .ms-title { font-family:var(--serif); font-style:italic; font-size:20px; margin:2px 0 4px; line-height:1.1; }
.ms .ms-meta { font-family:var(--mono); font-size:11px; opacity:.7; display:flex; gap:14px; }
.ms .ms-meta .gap { color:var(--ember); }

/* MODEL CARDS */
.model-cards { display:grid; grid-template-columns:repeat(4, 1fr); gap:10px; }
.model-card { border:1px solid var(--line); border-radius:4px; padding:18px; display:flex; flex-direction:column; gap:6px; min-height:130px; }
.model-card.planner { background:var(--mustard); }
.model-card.coder   { background:var(--ember); }
.model-card.vision  { background:var(--dusk); }
.model-card.fast    { background:var(--mint); }
.model-card .role { font-family:var(--mono); font-size:10px; letter-spacing:.14em; text-transform:uppercase; opacity:.6; }
.model-card .name { font-family:var(--serif); font-size:26px; line-height:1; }
.model-card .name em { font-style:italic; }
.model-card .toks { font-family:var(--serif); font-size:20px; }
.model-card .toks .car { color:var(--ink); font-size:13px; vertical-align:6px; }
.model-card .meta { font-family:var(--mono); font-size:10px; opacity:.65; margin-top:auto; }

/* COMMIT SPARKLINE */
.commit-spark { width:100%; height:50px; }
.commit-spark .line { fill:none; stroke:currentColor; stroke-width:1.5; }

/* PROJECT TAGS */
.proj-tags { display:flex; flex-wrap:wrap; gap:4px; margin-top:4px; }
.proj-tag { font-family:var(--mono); font-size:9px; letter-spacing:.1em; padding:2px 7px; border-radius:999px; border:1px solid var(--line); background:rgba(0,0,0,.08); text-transform:lowercase; }
.card.char .proj-tag, .card.olive .proj-tag { background:rgba(255,255,255,.08); border-color:rgba(255,255,255,.2); }
"""


# ── Main serve() ─────────────────────────────────────────────────────────────

def serve(port: int = 7432, extra_dirs: list[str] | None = None) -> None:
    from flask import Flask, request, redirect, Response, jsonify
    import webbrowser, threading

    app = Flask(__name__)

    def _load_all_summaries() -> list[dict]:
        summaries = []
        seen: set[str] = set()
        paths: list[Path] = []
        for key, info in _load_registry().items():
            p = Path(info["path"])
            if p.exists():
                paths.append(p)
        if extra_dirs:
            for d in extra_dirs:
                p = Path(d).resolve()
                if p.exists() and (p / "project.json").exists():
                    paths.append(p)
        for p in paths:
            sp = str(p.resolve())
            if sp in seen:
                continue
            seen.add(sp)
            s = _project_summary(p)
            if s:
                summaries.append(s)
        return summaries

    @app.route("/")
    def index():
        summaries = _load_all_summaries()

        if not summaries:
            cards_html = '<div style="grid-column:1/-1;padding:80px;text-align:center;color:rgba(20,20,20,.4);font-family:var(--serif);font-size:24px;font-style:italic">No projects yet — run <code style=\'font-family:var(--mono);font-size:16px\'>sarathi init</code> to begin.</div>'
        else:
            # Assign layouts and colors
            sorted_s = sorted(summaries, key=lambda s: (-len(s.get("milestones",[])), -s.get("gen_count",0)))
            card_htmls = []
            has_large = False
            for i, s in enumerate(sorted_s):
                is_display = not has_large and s.get("gen_count", 0) > 0
                if is_display:
                    has_large = True
                    layout = "large display"
                elif s.get("gen_count", 0) == 0:
                    layout = "small"
                elif i == 1:
                    layout = "wide"
                else:
                    layout = "medium"
                color = _project_color(s["name"], s.get("domain","auto"), i)
                card_htmls.append(_card_html(s, color, layout, is_display))
            cards_html = "\n".join(card_htmls)

        # Global stats
        total_projects = len(summaries)
        total_slides   = sum(s.get("slide_count", 0) for s in summaries)
        total_gens     = sum(s.get("gen_count", 0) for s in summaries)
        total_ms       = sum(len(s.get("milestones",[])) for s in summaries)
        streak         = _compute_streak(summaries)
        last_gen_dur   = "—"
        for s in summaries:
            for e in reversed(s.get("gen_events", [])):
                d = e.get("duration_s", 0)
                if d:
                    last_gen_dur = f"{d:.0f}s"
                    break
            if last_gen_dur != "—":
                break

        # Wrapped & insight
        wrapped = _compute_weekly_wrapped(summaries)
        insight = _compute_insight(summaries, wrapped)

        # Quote of the day
        q_idx = datetime.now().toordinal() % len(_QUOTES)
        q_text, q_attr, _ = _QUOTES[q_idx]

        # Achievements
        achievements = _compute_achievements(summaries)
        ach_html = "".join(
            f'<div class="ach {"unlocked" if a["unlocked"] else "locked"}">'
            f'<div class="ach-glyph">{a["glyph"]}</div>'
            f'<div class="ach-name">{a["name"]}</div>'
            f'<div class="ach-desc">{a["desc"]}</div>'
            f'</div>'
            for a in achievements
        )
        unlocked_count = sum(1 for a in achievements if a["unlocked"])

        html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Sarathi — Portfolio</title>
<meta name="viewport" content="width=1440"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,400;1,6..72,500&family=Bricolage+Grotesque:opsz,wght@12..96,300;12..96,400;12..96,500;12..96,600;12..96,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="frame"><div class="stage">

<header class="topbar">
  <div class="brand">
    <div class="brand-mark">s</div>
    <div>
      <div class="brand-name">Sarathi<span class="ast">*</span></div>
      <div class="brand-sub">Local CLI Companion · v0.2.0</div>
    </div>
  </div>
  <div class="status-row" id="status-row">
    <span class="pill"><span class="dot" id="ollama-dot"></span> Ollama <code id="ollama-model">checking…</code><span class="meta" id="ollama-ram"></span></span>
    <span class="pill" id="watcher-pill" style="display:none"><span class="dot warn"></span> <span id="watcher-count">0</span> watching</span>
    <span class="pill" id="gen-pill" style="display:none"><span class="dot gen"></span> Generating · <code id="gen-project">—</code></span>
  </div>
  <div class="global-stats">
    <div class="gs-cell"><div class="gs-num">{total_projects:02d}</div><div class="gs-lbl">Projects</div></div>
    <div class="gs-cell"><div class="gs-num">{total_slides:,}</div><div class="gs-lbl">Slides ever</div></div>
    <div class="gs-cell"><div class="gs-num">{streak}d</div><div class="gs-lbl">Streak</div></div>
    <div class="gs-cell"><div class="gs-num">{last_gen_dur}</div><div class="gs-lbl">Last gen</div></div>
  </div>
</header>

<div class="insight" id="insight">
  <div class="insight-tag">Sarathi observes</div>
  <div class="insight-text">{insight}</div>
  <div class="insight-time">{datetime.now().strftime('%H:%M')} · auto-refreshes on load</div>
  <button class="insight-close" onclick="this.closest('.insight').style.display='none'">×</button>
</div>

<div class="toolbar">
  <div class="search">
    <span style="opacity:.5">⌕</span>
    <input id="search-input" placeholder="Search projects, files, milestones…" oninput="filterCards(this.value)"/>
    <span class="kbd">/</span>
  </div>
  <div class="filter-chips">
    <button class="chip active" onclick="setFilter('all',this)">all</button>
    <button class="chip" onclick="setFilter('ml',this)">ml</button>
    <button class="chip" onclick="setFilter('software',this)">software</button>
    <button class="chip" onclick="setFilter('data',this)">data</button>
    <button class="chip" onclick="setFilter('pending',this)">pending</button>
  </div>
  <button class="sort-btn">last activity</button>
</div>

<div class="wrapped" id="wrapped">
  <div class="wrapped-label">This week<span class="ast">,</span></div>
  <div class="wrapped-stats">
    <div class="ws"><div class="ws-num"><span class="car">^</span>{wrapped["slides"]}</div><div class="ws-lbl">Slides</div></div>
    <div class="ws"><div class="ws-num">{wrapped["gens"]}</div><div class="ws-lbl">Generations</div></div>
    <div class="ws"><div class="ws-num" style="font-size:16px">{wrapped["fav_model"]}</div><div class="ws-lbl">Fav model</div></div>
    <div class="ws"><div class="ws-num">{wrapped["best_day"]}</div><div class="ws-lbl">Best day</div></div>
    <div class="ws"><div class="ws-num">{wrapped["streak"]}d</div><div class="ws-lbl">Streak</div></div>
  </div>
  <button class="wrapped-close" onclick="this.closest('.wrapped').style.display='none'">×</button>
</div>

<div class="bento" id="bento">{cards_html}</div>

<div class="personality">
  <div class="achievements">
    <div class="section-h">
      <h3>Achievements <span class="ast">*</span></h3>
      <div class="meta">{unlocked_count} of {len(achievements)} unlocked</div>
    </div>
    <div class="badge-grid">{ach_html}</div>
  </div>
  <div class="quote">
    <div>
      <div class="quote-mark">"</div>
      <div class="quote-body">{q_text}</div>
    </div>
    <div class="quote-attr">— {q_attr} · rotates daily</div>
  </div>
</div>

<div class="kbd-bar">
  <span class="pair"><span class="k">/</span> Search</span>
  <span class="pair"><span class="k">R</span> Refresh</span>
  <span class="pair"><span class="k">?</span> Shortcuts</span>
  <span style="margin-left:auto;font-family:var(--mono);font-size:11px;opacity:.5">v0.2.0 · localhost:{port}</span>
</div>
</div></div>

<button class="float-help" onclick="location.reload()"><span class="k">↻</span> refresh</button>

<script>
let activeFilter = 'all';

function filterCards(q) {{
  document.querySelectorAll('.card').forEach(c => {{
    const text = c.textContent.toLowerCase();
    const domain = c.dataset.domain || '';
    const hasPending = c.querySelector('.pending-flag');
    const matchQ = !q || text.includes(q.toLowerCase());
    const matchD = activeFilter === 'all' ||
                   (activeFilter === 'pending' ? !!hasPending : domain === activeFilter);
    c.classList.toggle('hidden', !matchQ || !matchD);
  }});
}}

function setFilter(f, btn) {{
  activeFilter = f;
  document.querySelectorAll('.chip').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterCards(document.getElementById('search-input').value);
}}

function openDetail(path) {{
  window.location.href = '/detail?path=' + encodeURIComponent(path);
}}

function copyCmd(el, cmd) {{
  navigator.clipboard.writeText(cmd);
  const old = el.textContent;
  el.textContent = 'copied!';
  setTimeout(() => el.textContent = old, 1400);
}}

document.addEventListener('keydown', e => {{
  if (e.target.matches('input,textarea')) return;
  if (e.key === '/') {{ e.preventDefault(); document.getElementById('search-input').focus(); }}
  if (e.key === 'r' || e.key === 'R') location.reload();
}});

async function pollStatus() {{
  try {{
    const r = await fetch('/api/status');
    const d = await r.json();

    // Ollama pill
    const dot = document.getElementById('ollama-dot');
    const modelEl = document.getElementById('ollama-model');
    const ramEl = document.getElementById('ollama-ram');
    if (dot) dot.style.background = d.ollama?.running ? '#4caf50' : '#f06060';
    if (modelEl) modelEl.textContent = d.ollama?.loaded_model || (d.ollama?.running ? 'idle' : 'offline');
    if (ramEl) ramEl.textContent = d.ollama?.ram_gb > 0 ? d.ollama.ram_gb + ' GB' : '';

    // Watchers pill
    const wp = document.getElementById('watcher-pill');
    const wc = document.getElementById('watcher-count');
    if (wp && wc) {{
      const n = (d.watchers || []).length;
      wc.textContent = n;
      wp.style.display = n > 0 ? '' : 'none';
    }}

    // Gen pill (live generation or queue worker)
    const gp    = document.getElementById('gen-pill');
    const gproj = document.getElementById('gen-project');
    if (gp && gproj) {{
      const gen = (d.generating || []);
      const qjob = d.queue?.running_job;
      const qn   = d.queue?.queued_count || 0;
      if (gen.length > 0) {{
        gp.style.display = '';
        const qsuffix = qn > 0 ? ` (+${{qn}} queued)` : '';
        gproj.textContent = (gen[0].name || '—') + qsuffix;
      }} else if (qjob) {{
        gp.style.display = '';
        gproj.textContent = (qjob.project ? qjob.project.split('/').pop() : '—')
                          + (qn > 0 ? ` (+${{qn}} queued)` : '');
      }} else if (d.queue?.worker_running) {{
        gp.style.display = '';
        gproj.textContent = `worker running · ${{qn}} queued`;
      }} else {{
        gp.style.display = 'none';
      }}
    }}
  }} catch(e) {{}}
}}
pollStatus();
setInterval(pollStatus, 5000);
</script>
</body></html>"""
        return Response(html, content_type="text/html")

    @app.route("/detail")
    def detail():
        path = request.args.get("path", "")
        p = Path(path)
        if not p.exists():
            return "Project not found", 404
        s = _project_summary(p)
        if not s:
            return "No project.json found", 404
        git = _get_git_details(p)
        files = _get_file_details(p)
        html = _detail_page_html(s, git, files, _CSS)
        return Response(html, content_type="text/html")

    @app.route("/open")
    def open_file():
        path = request.args.get("path", "")
        if path and Path(path).exists():
            return redirect(f"file://{path}")
        return "Not found", 404

    @app.route("/api/status")
    def api_status():
        from . import tracker as trk
        from . import jobs as _jobs

        ollama_status = _get_ollama_status()
        watchers   = []
        generating = []
        all_paths: list[Path] = []
        for key, info in _load_registry().items():
            p = Path(info["path"])
            if p.exists():
                all_paths.append(p)
        for p in all_paths:
            pid_info = trk.read_pid(p)
            if pid_info:
                watchers.append({"name": p.name, "path": str(p), "since": pid_info.get("started", "")})
            status = trk.read_status(p)
            if status.get("state") == "generating":
                generating.append({"name": p.name, "path": str(p), "model": status.get("model", "")})

        queue   = _jobs.get_queue()
        worker  = _jobs.is_worker_running()
        queued  = [j for j in queue if j.get("status") == "queued"]
        running_jobs = [j for j in queue if j.get("status") == "running"]

        return jsonify({
            "ollama":   ollama_status,
            "watchers": watchers,
            "generating": generating,
            "queue": {
                "worker_running": worker,
                "queued_count":   len(queued),
                "running_job":    running_jobs[0] if running_jobs else None,
                "jobs": queued[:5],
            },
        })

    url = f"http://localhost:{port}"
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"\n  Sarathi Portfolio  →  {url}\n  Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
