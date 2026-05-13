# Sarathi

Sarathi (Sanskrit: *the charioteer who guides*) turns raw project results into gorgeous, self-contained HTML + PDF presentations using a local LLM via Ollama.

## How it works

1. **Init** a project — creates a folder with structured subdirs and stores your project description as context.
2. **Drop results** — images, data files, notes, logs — into the folder.
3. **Make** — Sarathi scans everything, calls the local LLM, and generates a Reveal.js slide deck + PDF. It watches for changes and regenerates automatically.

```
sarathi init "my-experiment" "Comparing BERT vs GPT on IMDB sentiment across 3 seeds"
cp results/*.png my-experiment/plots/
cp metrics.csv   my-experiment/data/
sarathi make my-experiment/
```

Output lands in `my-experiment/output/`:
- `presentation.html` — Reveal.js slides, self-contained, open in any browser
- `presentation.pdf` — printable / shareable version

## Install

```bash
pip install -e .
playwright install chromium
```

Requires [Ollama](https://ollama.com) running locally with a vision-capable model:

```bash
ollama pull llama3.2-vision
```

## Commands

```
sarathi init NAME DESCRIPTION [--model MODEL]
sarathi make FOLDER [--once] [--model MODEL]
```

- `--once` — generate once and exit instead of watching for changes
- `--model` — override the Ollama model (default: `llama3.2-vision`)

## Result file types

| Location | Supported formats |
|----------|------------------|
| `plots/` | PNG, JPG, SVG |
| `data/`  | CSV, JSON, JSONL |
| `notes/` | Markdown, TXT, logs |
| anywhere | Python, shell scripts, notebooks |

## Project structure

```
project-folder/
├── project.json      # name, description, model (auto-created by init)
├── data/
├── plots/
├── notes/
└── output/
    ├── presentation.html
    └── presentation.pdf
```
