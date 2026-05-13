# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Sarathi** — a CLI tool that watches a project folder and generates Reveal.js + PDF presentations from result files (images, CSVs, text, logs) using a local LLM via Ollama.

## Commands

```bash
# Install
pip install -e .
playwright install chromium

# Usage
sarathi init "name" "description"          # scaffold project folder
sarathi init "name" "description" --model  # scaffold + persist model choice
sarathi make <folder>/                     # generate + watch (Ctrl-C to stop)
sarathi make <folder>/ --once              # one-shot generation
sarathi make <folder>/ --model <m>         # override Ollama model for this run
```

No test suite exists yet. No linter is configured in `pyproject.toml`.

## Architecture

```
src/sarathi/
├── cli.py       # click group with `init` and `make` subcommands
├── scanner.py   # walks project dir, categorizes files → list[ResultFile]
├── builder.py   # builds Ollama chat message, calls ollama.chat(), extracts HTML
├── exporter.py  # playwright: HTML → PDF
└── watcher.py   # watchdog observer with 3s debounce → calls generate()
```

**Data flow**: `make` → `scanner.scan()` → `builder.generate()` → writes `output/presentation.html` → `exporter.to_pdf()` → writes `output/presentation.pdf`. The watcher re-triggers this pipeline on any file change outside `output/`.

**LLM contract**: `builder.py` sends a single `ollama.chat()` call with a detailed system prompt instructing the model to return a complete, self-contained Reveal.js HTML document. The response is stripped of any markdown fences by `_extract_html()`.

**Model persistence**: `sarathi init --model <m>` stores the model name in `project.json`. `sarathi make` reads it from there, so `--model` only needs to be passed at `make` time when overriding.

**PDF rendering**: `exporter.py` waits for `networkidle` plus an additional 2 s before capturing, to allow CDN-loaded Reveal.js and Chart.js to fully render.

**Watcher skip list**: `output/`, `.git/`, `__pycache__/`, `.sarathi/` are ignored (`.sarathi/` is reserved for future per-project config).

## File scanning

`scanner.py` handles these extensions:

| Type   | Extensions                          | Limits                       |
|--------|-------------------------------------|------------------------------|
| image  | `.png` `.jpg` `.jpeg` `.gif` `.webp`| resized to max 1024 px, JPEG |
| svg    | `.svg`                              | base64 data URI              |
| data   | `.csv` `.json` `.jsonl` `.tsv`      | CSV capped at 150 rows       |
| text   | `.md` `.txt` `.log` `.rst`          | capped at 8000 chars         |
| code   | `.py` `.sh` `.bash` `.ipynb` `.r` `.sql` | capped at 8000 chars   |

`project.json` and any dotfile are skipped. Unknown extensions are silently ignored.

## Key dependencies

- `ollama` — Ollama Python client for local LLM
- `watchdog` — filesystem event monitoring
- `playwright` — headless Chromium for HTML→PDF
- `Pillow` — image resizing/encoding
- `click` + `rich` — CLI and terminal output

## Prerequisites

- Ollama running locally (`ollama serve`)
- Vision model pulled: `ollama pull llama3.2-vision`
- Chromium installed: `playwright install chromium`
