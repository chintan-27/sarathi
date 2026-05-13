from __future__ import annotations

import base64
import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

SKIP_DIRS = {"output", ".git", "__pycache__", ".sarathi"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
SVG_EXTS = {".svg"}
DATA_EXTS = {".csv", ".json", ".jsonl", ".tsv"}
TEXT_EXTS = {".md", ".txt", ".log", ".rst"}
CODE_EXTS = {".py", ".sh", ".bash", ".ipynb", ".r", ".sql"}
MAX_IMAGE_PX = 1024
MAX_CSV_ROWS = 150
MAX_TEXT_CHARS = 8000


@dataclass
class ResultFile:
    path: str
    filename: str
    type: str  # image | data | text | code | svg
    content: str  # text or base64 data URI for images


def scan(project_dir: Path) -> list[ResultFile]:
    results: list[ResultFile] = []
    for file in sorted(project_dir.rglob("*")):
        if not file.is_file():
            continue
        if any(part in SKIP_DIRS for part in file.parts):
            continue
        if file.name.startswith("."):
            continue
        if file.name == "project.json":
            continue

        ext = file.suffix.lower()
        rel = str(file.relative_to(project_dir))

        if ext in IMAGE_EXTS:
            rf = _load_image(file, rel)
        elif ext in SVG_EXTS:
            rf = _load_svg(file, rel)
        elif ext in DATA_EXTS:
            rf = _load_data(file, rel, ext)
        elif ext in TEXT_EXTS:
            rf = _load_text(file, rel, "text")
        elif ext in CODE_EXTS:
            rf = _load_text(file, rel, "code")
        else:
            continue

        if rf:
            results.append(rf)

    return results


def _load_image(path: Path, rel: str) -> ResultFile | None:
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return ResultFile(path=rel, filename=path.name, type="image",
                          content=f"data:image/jpeg;base64,{b64}")
    except Exception:
        return None


def _load_svg(path: Path, rel: str) -> ResultFile | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        b64 = base64.b64encode(text.encode()).decode()
        return ResultFile(path=rel, filename=path.name, type="svg",
                          content=f"data:image/svg+xml;base64,{b64}")
    except Exception:
        return None


def _load_data(path: Path, rel: str, ext: str) -> ResultFile | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if ext == ".csv":
            rows = list(csv.reader(io.StringIO(text)))
            total = len(rows)
            if total > MAX_CSV_ROWS + 1:
                rows = rows[: MAX_CSV_ROWS + 1]
                text = _rows_to_csv(rows) + f"\n... ({total - MAX_CSV_ROWS} more rows)"
        elif ext in (".json", ".jsonl"):
            try:
                parsed = json.loads(text)
                text = json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                pass
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + "\n... (truncated)"
        return ResultFile(path=rel, filename=path.name, type="data", content=text)
    except Exception:
        return None


def _load_text(path: Path, rel: str, kind: str) -> ResultFile | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + "\n... (truncated)"
        return ResultFile(path=rel, filename=path.name, type=kind, content=text)
    except Exception:
        return None


def _rows_to_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue()
