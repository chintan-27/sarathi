from __future__ import annotations

import base64
import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

SKIP_DIRS = {"output", ".git", "__pycache__", ".sarathi", "research", "node_modules", ".venv", "venv"}
IMAGE_EXTS  = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
SVG_EXTS    = {".svg"}
DATA_EXTS   = {".csv", ".json", ".jsonl", ".tsv"}
TEXT_EXTS   = {".md", ".txt", ".log", ".rst", ".out", ".err", ".cast"}
CODE_EXTS   = {".py", ".sh", ".bash", ".r", ".sql", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".c"}
NOTEBOOK_EXT = ".ipynb"
HTML_SCREENSHOT_EXTS = {".html", ".htm"}  # auto-screenshot these
MAX_IMAGE_PX  = 1280
MAX_CSV_ROWS  = 200
MAX_TEXT_CHARS = 10000


@dataclass
class ResultFile:
    path: str
    filename: str
    type: str  # image | data | text | code | svg | screenshot
    content: str  # text or base64 data URI for images


# High-priority context files — scanned first
_PRIORITY_FILES = {"CLAUDE.md", "README.md", "readme.md", "claude.md"}

# Screenshot directories — HTML files here get auto-screenshotted
_SCREENSHOT_DIRS = {"screenshots", "screens", "captures", "demos", "preview"}


def scan(project_dir: Path) -> list[ResultFile]:
    results: list[ResultFile] = []

    # Priority files first
    for name in _PRIORITY_FILES:
        f = project_dir / name
        if f.exists() and f.is_file():
            rel = str(f.relative_to(project_dir))
            rf = _load_text(f, rel, "text")
            if rf:
                results.append(rf)

    for file in sorted(project_dir.rglob("*")):
        if not file.is_file():
            continue
        if any(part in SKIP_DIRS for part in file.parts):
            continue
        if file.name.startswith("."):
            continue
        if file.name in {"project.json"} | _PRIORITY_FILES:
            continue

        ext = file.suffix.lower()
        rel = str(file.relative_to(project_dir))

        # Any parent dir named screenshots/demos → auto-screenshot HTML
        in_screenshot_dir = any(p in _SCREENSHOT_DIRS for p in file.parts)

        if ext in IMAGE_EXTS:
            rf = _load_image(file, rel)
        elif ext in SVG_EXTS:
            rf = _load_svg(file, rel)
        elif ext in DATA_EXTS:
            rf = _load_data(file, rel, ext)
        elif ext in TEXT_EXTS:
            rf = _load_text(file, rel, "text")
        elif ext == NOTEBOOK_EXT:
            rf = _load_notebook(file, rel)
        elif ext in CODE_EXTS:
            rf = _load_text(file, rel, "code")
        elif ext in HTML_SCREENSHOT_EXTS and in_screenshot_dir:
            rf = _screenshot_html(file, rel, project_dir)
        else:
            continue

        if rf:
            results.append(rf)

    return results


# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_image(path: Path, rel: str) -> ResultFile | None:
    try:
        img = Image.open(path).convert("RGB")
        img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return ResultFile(path=rel, filename=path.name, type="image",
                          content=f"data:image/jpeg;base64,{b64}")
    except Exception:
        return None


def _load_svg(path: Path, rel: str) -> ResultFile | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        b64  = base64.b64encode(text.encode()).decode()
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
                rows = rows[:MAX_CSV_ROWS + 1]
                text = _rows_to_csv(rows) + f"\n... ({total - MAX_CSV_ROWS} more rows)"
        elif ext in (".json", ".jsonl"):
            try:
                parsed = json.loads(text)
                text   = json.dumps(parsed, indent=2)
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


def _load_notebook(path: Path, rel: str) -> ResultFile | None:
    """Extract meaningful content from a Jupyter notebook.

    Instead of dumping raw JSON, pull:
    - Markdown cells (narrative)
    - Code cells (logic)
    - Cell outputs: text, images, error tracebacks
    """
    try:
        nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        parts: list[str] = []
        image_results: list[ResultFile] = []

        for i, cell in enumerate(nb.get("cells", []), 1):
            ctype   = cell.get("cell_type", "")
            source  = "".join(cell.get("source", []))
            outputs = cell.get("outputs", [])

            if ctype == "markdown" and source.strip():
                parts.append(f"### Markdown\n{source.strip()}")

            elif ctype == "code" and source.strip():
                parts.append(f"### Code (cell {i})\n```python\n{source.strip()}\n```")

                for out in outputs:
                    otype = out.get("output_type", "")

                    # Plain text output
                    if otype in ("stream", "execute_result", "display_data"):
                        text_lines = out.get("text", out.get("data", {}).get("text/plain", []))
                        if isinstance(text_lines, list):
                            text_lines = "".join(text_lines)
                        if text_lines and text_lines.strip():
                            parts.append(f"**Output:**\n```\n{text_lines.strip()[:800]}\n```")

                        # Embedded image output
                        img_b64 = out.get("data", {}).get("image/png") or out.get("data", {}).get("image/jpeg")
                        if img_b64:
                            if isinstance(img_b64, list):
                                img_b64 = "".join(img_b64)
                            fmt = "png" if "image/png" in out.get("data", {}) else "jpeg"
                            # Resize the embedded image
                            try:
                                raw = base64.b64decode(img_b64)
                                img = Image.open(io.BytesIO(raw)).convert("RGB")
                                img.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX), Image.LANCZOS)
                                buf = io.BytesIO()
                                img.save(buf, format="JPEG", quality=88)
                                b64 = base64.b64encode(buf.getvalue()).decode()
                                img_rel = f"{rel}::cell{i}_output.jpg"
                                image_results.append(ResultFile(
                                    path=img_rel,
                                    filename=f"{path.stem}_cell{i}.jpg",
                                    type="image",
                                    content=f"data:image/jpeg;base64,{b64}",
                                ))
                                parts.append(f"**Chart/Image output from cell {i}** — see embedded image above.")
                            except Exception:
                                pass

                    elif otype == "error":
                        tb = "\n".join(out.get("traceback", []))
                        # Strip ANSI escape codes
                        import re
                        tb = re.sub(r"\x1b\[[0-9;]*m", "", tb)
                        parts.append(f"**Error:**\n```\n{tb[:400]}\n```")

        combined = "\n\n".join(parts)
        if len(combined) > MAX_TEXT_CHARS:
            combined = combined[:MAX_TEXT_CHARS] + "\n... (truncated)"

        # Store notebook text + images as a composite
        # Return the text part; image_results are attached via side-channel
        # (store them on the ResultFile as a custom attribute via abuse of path field)
        result = ResultFile(path=rel, filename=path.name, type="code", content=combined)

        # Hack: attach extra images by yielding them separately via a module-level list
        if image_results:
            _notebook_images.extend(image_results)

        return result
    except Exception:
        return _load_text(path, rel, "code")  # fallback to raw


# Side-channel for notebook-extracted images (reset each scan)
_notebook_images: list[ResultFile] = []


def scan(project_dir: Path) -> list[ResultFile]:  # noqa: F811 (redefine with images)
    global _notebook_images
    _notebook_images = []

    results: list[ResultFile] = []

    # Priority files first
    for name in _PRIORITY_FILES:
        f = project_dir / name
        if f.exists() and f.is_file():
            rel = str(f.relative_to(project_dir))
            rf  = _load_text(f, rel, "text")
            if rf:
                results.append(rf)

    for file in sorted(project_dir.rglob("*")):
        if not file.is_file():
            continue
        if any(part in SKIP_DIRS for part in file.parts):
            continue
        if file.name.startswith("."):
            continue
        if file.name in {"project.json"} | _PRIORITY_FILES:
            continue

        ext = file.suffix.lower()
        rel = str(file.relative_to(project_dir))
        in_screenshot_dir = any(p in _SCREENSHOT_DIRS for p in file.parts)

        if ext in IMAGE_EXTS:
            rf = _load_image(file, rel)
        elif ext in SVG_EXTS:
            rf = _load_svg(file, rel)
        elif ext in DATA_EXTS:
            rf = _load_data(file, rel, ext)
        elif ext in TEXT_EXTS:
            rf = _load_text(file, rel, "text")
        elif ext == NOTEBOOK_EXT:
            rf = _load_notebook(file, rel)
        elif ext in CODE_EXTS:
            rf = _load_text(file, rel, "code")
        elif ext in HTML_SCREENSHOT_EXTS and in_screenshot_dir:
            rf = _screenshot_html(file, rel, project_dir)
        else:
            continue

        if rf:
            results.append(rf)

    # Append notebook-extracted images after their parent notebook
    results.extend(_notebook_images)

    return results


def _screenshot_html(path: Path, rel: str, project_dir: Path) -> ResultFile | None:
    """Screenshot an HTML file using Playwright and return as image."""
    try:
        from playwright.sync_api import sync_playwright
        shot_dir = project_dir / ".sarathi" / "screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        shot_path = shot_dir / (path.stem + ".jpg")

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page    = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"file://{path.resolve()}", wait_until="networkidle")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(shot_path), type="jpeg", quality=85,
                            full_page=False)
            browser.close()

        return _load_image(shot_path, f".sarathi/screenshots/{shot_path.name}")
    except Exception:
        return None


def _rows_to_csv(rows: list[list[str]]) -> str:
    buf    = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue()
