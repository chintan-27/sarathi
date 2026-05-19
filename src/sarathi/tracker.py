from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

_SARATHI_DIR = ".sarathi"
_TIMELINE_FILE = "timeline.jsonl"


def _sarathi_dir(project_dir: Path) -> Path:
    return project_dir / _SARATHI_DIR


def _timeline_path(project_dir: Path) -> Path:
    return _sarathi_dir(project_dir) / _TIMELINE_FILE


def init_tracker(project_dir: Path) -> None:
    sarathi = _sarathi_dir(project_dir)
    sarathi.mkdir(exist_ok=True)
    (sarathi / "viz").mkdir(exist_ok=True)
    timeline = _timeline_path(project_dir)
    if not timeline.exists():
        timeline.touch()


def log_event(project_dir: Path, event_type: str, **kwargs: Any) -> None:
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event_type}
    entry.update(kwargs)
    with _timeline_path(project_dir).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _file_hash(path: Path) -> str:
    try:
        h = hashlib.sha1(path.read_bytes(), usedforsecurity=False)
        return h.hexdigest()[:12]
    except Exception:
        return ""


_DEFAULT_SKIP_DIRS = {".sarathi", "output", ".git", "__pycache__", "node_modules"}
_MAX_FILE_BYTES = 50 * 1024 * 1024  # skip files larger than 50 MB


def _load_skip_dirs(project_dir: Path) -> set[str]:
    skip = set(_DEFAULT_SKIP_DIRS)
    pjson = project_dir / "project.json"
    if pjson.exists():
        try:
            import json as _json
            extra = _json.loads(pjson.read_text(encoding="utf-8")).get("skip_dirs", [])
            skip.update(extra)
        except Exception:
            pass
    return skip


def snapshot_hashes(project_dir: Path) -> dict[str, str]:
    import os
    hashes: dict[str, str] = {}
    skip = _load_skip_dirs(project_dir)
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fname in sorted(filenames):
            f = Path(dirpath) / fname
            try:
                if f.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            rel = str(f.relative_to(project_dir))
            hashes[rel] = _file_hash(f)
    return hashes


def get_timeline(project_dir: Path) -> list[dict]:
    path = _timeline_path(project_dir)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def get_milestones(project_dir: Path) -> list[dict]:
    return [e for e in get_timeline(project_dir) if e.get("event") == "milestone"]


def get_files_at_milestone(project_dir: Path, label: str) -> dict[str, str] | None:
    for event in get_timeline(project_dir):
        if event.get("event") == "milestone" and event.get("label") == label:
            return event.get("file_hashes", {})
    return None


def last_generated(project_dir: Path) -> str | None:
    for event in reversed(get_timeline(project_dir)):
        if event.get("event") == "generated":
            return event.get("ts")
    return None


def files_since_last_generated(project_dir: Path) -> list[str]:
    events = get_timeline(project_dir)
    last_gen_ts: str | None = None
    for e in reversed(events):
        if e.get("event") == "generated":
            last_gen_ts = e["ts"]
            break
    if last_gen_ts is None:
        return []
    changed = []
    for e in events:
        if e["ts"] > last_gen_ts and e.get("event") in ("checkpoint", "file_added"):
            f = e.get("file")
            if f and f not in changed:
                changed.append(f)
    return changed


def get_personal_bests(project_dir: Path) -> dict:
    """Scan generated events and return all-time personal bests."""
    from datetime import datetime
    bests: dict = {
        "fastest_s": None,
        "best_tok_s": None,
        "largest_slides": None,
        "best_day": None,
        "best_day_count": 0,
    }
    day_counts: dict[str, int] = {}
    for e in get_timeline(project_dir):
        if e.get("event") != "generated":
            continue
        tok_s = e.get("tok_s")
        duration_s = e.get("duration_s")
        slides = e.get("slide_count")
        ts = e.get("ts", "")[:10]
        if tok_s and (bests["best_tok_s"] is None or tok_s > bests["best_tok_s"]):
            bests["best_tok_s"] = round(tok_s, 1)
        if duration_s and duration_s > 0 and (bests["fastest_s"] is None or duration_s < bests["fastest_s"]):
            bests["fastest_s"] = round(duration_s, 1)
        if slides and (bests["largest_slides"] is None or slides > bests["largest_slides"]):
            bests["largest_slides"] = slides
        if ts:
            day_counts[ts] = day_counts.get(ts, 0) + 1
    if day_counts:
        best_day = max(day_counts, key=lambda d: day_counts[d])
        bests["best_day"] = best_day
        bests["best_day_count"] = day_counts[best_day]
    return bests


def write_status(project_dir: Path, **kwargs: Any) -> None:
    """Write .sarathi/status.json with current generation state."""
    import json as _json
    status_path = _sarathi_dir(project_dir) / "status.json"
    data = {"ts": datetime.now().isoformat(timespec="seconds")}
    data.update(kwargs)
    try:
        status_path.write_text(_json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def read_status(project_dir: Path) -> dict:
    """Read .sarathi/status.json, return {} if missing."""
    import json as _json
    status_path = _sarathi_dir(project_dir) / "status.json"
    if not status_path.exists():
        return {}
    try:
        return _json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_pid(project_dir: Path, pid: int) -> None:
    """Write .sarathi/watcher.pid so portfolio can detect active watchers."""
    import json as _json
    pid_path = _sarathi_dir(project_dir) / "watcher.pid"
    try:
        pid_path.write_text(
            _json.dumps({"pid": pid, "started": datetime.now().isoformat(timespec="seconds")}),
            encoding="utf-8",
        )
    except Exception:
        pass


def clear_pid(project_dir: Path) -> None:
    """Remove .sarathi/watcher.pid on watcher exit."""
    pid_path = _sarathi_dir(project_dir) / "watcher.pid"
    try:
        pid_path.unlink(missing_ok=True)
    except Exception:
        pass


def read_pid(project_dir: Path) -> dict | None:
    """Read .sarathi/watcher.pid; verify process is still alive. Returns None if dead."""
    import json as _json
    import os
    pid_path = _sarathi_dir(project_dir) / "watcher.pid"
    if not pid_path.exists():
        return None
    try:
        data = _json.loads(pid_path.read_text(encoding="utf-8"))
        pid = data.get("pid")
        if pid:
            os.kill(pid, 0)  # raises if process dead
        return data
    except Exception:
        return None


# ── Versioned output snapshots ────────────────────────────────────────────────

def _slugify(label: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug[:32]


def get_version_dirs(project_dir: Path) -> list[Path]:
    """Return all versioned output dirs sorted by version number."""
    out = project_dir / "output"
    if not out.exists():
        return []
    dirs = sorted(
        (d for d in out.iterdir() if d.is_dir() and d.name.startswith("v") and d.name[1:2].isdigit()),
        key=lambda d: int(d.name.split("-")[0][1:]) if d.name.split("-")[0][1:].isdigit() else 0,
    )
    return dirs


def get_next_version(project_dir: Path) -> int:
    return len(get_version_dirs(project_dir)) + 1


def get_versions(project_dir: Path) -> list[dict]:
    """Return metadata for all versioned output snapshots."""
    versions = []
    for d in get_version_dirs(project_dir):
        meta_path = d / "meta.json"
        if meta_path.exists():
            try:
                versions.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        else:
            versions.append({"version": d.name, "dir": str(d)})
    return versions


def snapshot_output_version(
    project_dir: Path,
    milestone_label: str,
    gen_stats: dict | None = None,
) -> Path | None:
    """Copy current output/presentation.* into output/vN-slug/ and write meta.json.

    Returns the version directory, or None if nothing to snapshot.
    """
    import shutil
    out = project_dir / "output"
    html = out / "presentation.html"
    if not html.exists():
        return None

    n     = get_next_version(project_dir)
    slug  = _slugify(milestone_label)
    vdir  = out / f"v{n}-{slug}"
    vdir.mkdir(parents=True, exist_ok=True)

    # Copy all presentation output files
    for fname in ("presentation.html", "presentation.pdf", "presentation.pptx"):
        src = out / fname
        if src.exists():
            shutil.copy2(src, vdir / fname)

    # Write version meta
    meta = {
        "version":   n,
        "dir":       str(vdir),
        "milestone": milestone_label,
        "ts":        datetime.now().isoformat(timespec="seconds"),
        "html_path": str(vdir / "presentation.html"),
        "slide_count": gen_stats.get("slide_count", 0) if gen_stats else 0,
        "model":     gen_stats.get("model", "") if gen_stats else "",
        "tok_s":     gen_stats.get("tok_s", 0) if gen_stats else 0,
        "duration_s":gen_stats.get("duration_s", 0) if gen_stats else 0,
    }
    (vdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return vdir


def get_delta_since_last_milestone(project_dir: Path) -> dict:
    """Compute what changed since the previous milestone snapshot.

    Returns a dict with: new_files, modified_files, commit_count, prev_milestone, prev_version.
    Used by builder to create a recap slide.
    """
    events    = get_timeline(project_dir)
    milestones = [e for e in events if e.get("event") == "milestone"]

    if len(milestones) < 2:
        return {}  # not enough history for a meaningful recap

    prev_ms = milestones[-2]
    curr_ms = milestones[-1]
    prev_hashes: dict[str, str] = prev_ms.get("file_hashes", {})
    curr_hashes: dict[str, str] = curr_ms.get("file_hashes", {})

    new_files      = [f for f in curr_hashes if f not in prev_hashes]
    modified_files = [f for f in curr_hashes if f in prev_hashes and curr_hashes[f] != prev_hashes[f]]
    deleted_files  = [f for f in prev_hashes if f not in curr_hashes]

    # Count commits between timestamps
    commit_count = 0
    prev_ts = prev_ms.get("ts", "")
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-list", "--count", f"--after={prev_ts}", "HEAD"],
            cwd=str(project_dir), capture_output=True, text=True, timeout=4,
        )
        commit_count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
    except Exception:
        pass

    # Find previous version number
    prev_versions = get_version_dirs(project_dir)
    prev_version_num = len(prev_versions)  # the one just snapshotted

    return {
        "prev_milestone":  prev_ms.get("label", ""),
        "curr_milestone":  curr_ms.get("label", ""),
        "prev_version":    prev_version_num,
        "new_files":       new_files[:10],
        "modified_files":  modified_files[:10],
        "deleted_files":   deleted_files[:5],
        "commit_count":    commit_count,
        "days_elapsed":    _days_between(prev_ms.get("ts", ""), curr_ms.get("ts", "")),
    }


def _days_between(ts1: str, ts2: str) -> int:
    try:
        d1 = datetime.fromisoformat(ts1).date()
        d2 = datetime.fromisoformat(ts2).date()
        return abs((d2 - d1).days)
    except Exception:
        return 0
