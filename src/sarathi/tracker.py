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


def snapshot_hashes(project_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    skip = {".sarathi", "output", ".git", "__pycache__"}
    for f in sorted(project_dir.rglob("*")):
        if not f.is_file():
            continue
        if any(part in skip for part in f.parts):
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
