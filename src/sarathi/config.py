from __future__ import annotations

import json
from pathlib import Path

_GLOBAL_CONFIG_DIR = Path.home() / ".config" / "sarathi"
_SARATHI_DIR = ".sarathi"

DEFAULTS: dict = {
    "model":          "qwen2.5-coder:3b",  # fallback if roles not set
    "planner_model":  "gemma3:4b",          # Pass 1: narrative outline
    "coder_model":    "qwen2.5-coder:3b",   # Pass 2: HTML/JS rendering
    "vision_model":   "gemma3:4b",          # image description (multimodal)
    "theme":          "dark-gradient",
    "domain":         "auto",
}


def _sarathi_dir(project_dir: Path) -> Path:
    return project_dir / _SARATHI_DIR


def load_project_config(project_dir: Path) -> dict:
    merged = dict(DEFAULTS)

    global_path = _GLOBAL_CONFIG_DIR / "config.json"
    if global_path.exists():
        try:
            merged.update(json.loads(global_path.read_text()))
        except Exception:
            pass

    local_path = _sarathi_dir(project_dir) / "config.json"
    if local_path.exists():
        try:
            merged.update(json.loads(local_path.read_text()))
        except Exception:
            pass

    return merged


def save_project_config(project_dir: Path, data: dict) -> None:
    local_path = _sarathi_dir(project_dir) / "config.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if local_path.exists():
        try:
            existing = json.loads(local_path.read_text())
        except Exception:
            pass
    existing.update(data)
    local_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
