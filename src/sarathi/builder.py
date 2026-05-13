from __future__ import annotations

import re
from pathlib import Path

import ollama

from .scanner import ResultFile

SYSTEM_PROMPT = """\
You are an expert presentation designer and data storyteller.
Your job is to transform raw project results (data, images, notes, code output) into \
a single, self-contained, gorgeous Reveal.js HTML presentation.

RULES:
1. Output ONLY the complete HTML document — no prose, no markdown fences, no explanation.
2. Use Reveal.js 4.x from CDN: https://unpkg.com/reveal.js@4/
3. Use the "moon" built-in theme as the base.
4. Add inline <style> for extra polish:
   - Import "Inter" from Google Fonts for body, "JetBrains Mono" for code
   - Large, high-contrast headings
   - Subtle gradient or dark background per slide when appropriate
   - Generous padding, clean layout
5. For CSV/tabular data: render as a Chart.js chart (CDN) inline in a <canvas>.
   Pick the chart type that best fits the data (bar, line, scatter, etc.).
6. For images (provided as base64 data URIs): embed as <img src="..."> — do NOT re-encode.
7. For SVG images: embed as <img src="..."> using the provided data URI.
8. Include these slide types in order:
   a. Title slide — project name, one-line description, date
   b. Context/Motivation — why this project matters (1-2 sentences)
   c. One slide per major result/finding — explain WHAT it shows AND WHY it matters
   d. Key Takeaways — bullet list of the 3-5 most important findings
   e. Next Steps or Open Questions (if inferable from the results)
9. Each slide must have <aside class="notes"> with 2-3 sentences of speaker notes.
10. Be THOROUGH: interpret the results, draw conclusions, highlight patterns.
    Do not just describe — EXPLAIN significance.
11. Keep slide text concise (max 5 bullet points per slide), but make notes rich.
12. The final HTML must work offline except for CDN resources.
"""


def _build_user_message(project_name: str, description: str,
                         files: list[ResultFile]) -> list[dict]:
    parts: list[dict] = []

    intro = (
        f"Project: {project_name}\n"
        f"Description: {description}\n\n"
        f"I have {len(files)} result file(s). Generate a comprehensive presentation.\n\n"
    )

    text_sections: list[str] = [intro]
    images: list[dict] = []

    for rf in files:
        if rf.type == "image":
            text_sections.append(f"[IMAGE: {rf.path}]")
            images.append({
                "type": "image_url",
                "image_url": {"url": rf.content},
            })
        elif rf.type in ("svg",):
            text_sections.append(
                f"[SVG IMAGE: {rf.path}]\n"
                f"Embed using this data URI: {rf.content[:80]}..."
            )
        elif rf.type == "data":
            text_sections.append(
                f"--- DATA FILE: {rf.path} ---\n{rf.content}\n"
            )
        elif rf.type == "text":
            text_sections.append(
                f"--- NOTE: {rf.path} ---\n{rf.content}\n"
            )
        elif rf.type == "code":
            text_sections.append(
                f"--- CODE: {rf.path} ---\n```\n{rf.content}\n```\n"
            )

    combined_text = "\n".join(text_sections)
    parts.append({"type": "text", "text": combined_text})
    parts.extend(images)

    return parts


def generate(project_name: str, description: str, files: list[ResultFile],
             model: str, output_html: Path) -> None:
    user_parts = _build_user_message(project_name, description, files)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_parts},
    ]

    response = ollama.chat(model=model, messages=messages)
    html = response.message.content

    html = _extract_html(html)
    output_html.write_text(html, encoding="utf-8")


def _extract_html(text: str) -> str:
    # If model wrapped output in a markdown fence, strip it
    fence = re.search(r"```(?:html)?\s*(<!DOCTYPE.*)", text, re.DOTALL | re.IGNORECASE)
    if fence:
        inner = fence.group(1)
        closing = inner.rfind("```")
        if closing != -1:
            inner = inner[:closing]
        return inner.strip()

    # Otherwise find the first DOCTYPE / html tag
    start = re.search(r"<!DOCTYPE|<html", text, re.IGNORECASE)
    if start:
        return text[start.start():].strip()

    return text.strip()
