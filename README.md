# Sarathi

Sarathi (Sanskrit: *the charioteer who guides*) is a CLI project companion that watches your work as it evolves, tracks milestones, and automatically generates polished **Reveal.js HTML + PPTX + PDF presentations** using a local LLM.

It works across three project types: ML experiments, software development, and data analysis — with a narrative style tailored to each.

---

## How it works

1. **Start a project** — Sarathi scaffolds a folder and stores your description as context
2. **Drop results** — images, CSVs, notebooks, logs, code — anywhere in the folder
3. **Track** — Sarathi watches for changes, logs a timeline, and lets you plant milestones
4. **Present** — a two-pass LLM pipeline generates a slide deck that tells the story of your work

```bash
sarathi arambh "bert-vs-gpt" "Comparing BERT and GPT on IMDB sentiment"
cp results/*.png  bert-vs-gpt/plots/
cp metrics.csv    bert-vs-gpt/data/
sarathi yatra bert-vs-gpt/          # watch + auto-generate on every change
sarathi chinh bert-vs-gpt/ --name "baseline done"
sarathi portfolio                   # dashboard at localhost:7432
```

Output in `bert-vs-gpt/output/`:
- `presentation.html` — Reveal.js slides with auto-animate, dark gradient theme
- `presentation.pdf` — printable version
- `presentation.pptx` — PowerPoint, shareable without a browser

---

## Install

```bash
pip install -e .
playwright install chromium
```

---

## Using Claude via Ollama

Sarathi uses the **Anthropic SDK pointed at Ollama's Anthropic-compatible API** — so you get Claude-quality output running entirely on your own machine, no cloud account needed.

### Quick setup

```bash
# Launch Claude Code through Ollama (handles env vars automatically)
ollama launch claude --model kimi-k2.5:cloud
```

This starts a session where Sarathi (and any tool using `ANTHROPIC_BASE_URL`) routes through Ollama to the model. Recommended models:

| Model | Best for | Notes |
|---|---|---|
| `kimi-k2.5:cloud` | HTML generation, long context | Best overall quality |
| `qwen3.5` | Fast local generation | Good structured output |
| `glm-5:cloud` | Reasoning-heavy decks | Strong narrative synthesis |
| `llama3.2-vision` | Image-heavy projects | Pull separately for vision |

### Manual setup (if not using `ollama launch claude`)

```bash
export ANTHROPIC_BASE_URL=http://localhost:11434
export ANTHROPIC_AUTH_TOKEN=ollama
export ANTHROPIC_API_KEY=""

sarathi rachna myproject/ --model kimi-k2.5:cloud
```

### Override model per project

```bash
# Set model at init time — saved to project.json
sarathi arambh "my-project" "description" --model qwen3.5

# Override for a single run
sarathi rachna myproject/ --model glm-5:cloud
```

---

## Commands

Every command has an English name and a Sanskrit alias — both work identically.

### Project lifecycle

| Command | Alias | What it does |
|---|---|---|
| `sarathi init NAME DESC` | `arambh` | Scaffold a new project folder |
| `sarathi track FOLDER` | `yatra` | Watch + auto-generate on file changes |
| `sarathi make FOLDER` | `rachna` | Generate once (no watching) |
| `sarathi mark FOLDER --name "label"` | `chinh` | Plant a milestone in the timeline |
| `sarathi log FOLDER` | `itihas` | Print the full project timeline |
| `sarathi status FOLDER` | `sthiti` | Show current state and pending changes |
| `sarathi open FOLDER` | `darshan` | Open latest presentation in browser |
| `sarathi diff FOLDER --from M1 --to M2` | `antar` | Generate a progress deck between milestones |

### Output & utilities

| Command | What it does |
|---|---|
| `sarathi portfolio` | Launch project dashboard at `localhost:7432` |
| `sarathi export FOLDER --format html\|pdf\|zip` | Re-export without re-generating |
| `sarathi theme FOLDER --set dark-gradient\|dracula\|light\|minimal` | Change slide theme |
| `sarathi models` | List Ollama models, flag vision-capable ones |
| `sarathi pull MODEL` | Pull an Ollama model with progress |
| `sarathi clean FOLDER` | Wipe `output/` and `.sarathi/viz/` cache |

### Key flags

| Flag | Command | Effect |
|---|---|---|
| `--model MODEL` | `track`, `make`, `rachna`, `yatra` | Override model for this run |
| `--once` | `track`, `yatra` | Generate once, then exit |
| `--edit-outline` | `track`, `make` | Save JSON outline to `.sarathi/outline.json` before rendering — edit it, then re-run without this flag |

---

## Generation pipeline

Sarathi uses a **two-pass approach** — the same pattern used by research systems like PPTAgent and ArcDeck — which produces significantly better output than single-pass generation:

```
scanner.scan()          → list of result files (images, CSVs, text, code)
viz.process()           → pre-render CSVs to chart PNGs (heuristic chart selection)
builder._generate_outline()  → Pass 1: LLM produces a JSON narrative outline
builder._render_slide()      → Pass 2: one LLM call per slide → HTML <section>
pptx_exporter.to_pptx()     → convert outline + artifacts → .pptx
exporter.to_pdf()       → Playwright → PDF
```

**Domain detection** — Sarathi reads your project description and file types to pick the right narrative arc:
- `ml` → Pyramid arc: hypothesis → experiments → ablation → final model
- `software` → Diamond arc: problem anecdote → systemic implications → resolution
- `data` → Inverted Pyramid: key finding first, then supporting evidence

**Visualization pipeline** — CSVs are pre-rendered to charts before the LLM sees them, using pandas dtype heuristics:

| Data shape | Chart |
|---|---|
| datetime column + numeric | Line chart |
| 2 numeric, high cardinality | Scatter plot |
| 3+ numeric columns | Correlation heatmap |
| Categorical + numeric, low cardinality | Horizontal bar chart |
| Part-to-whole data | Stacked bar |
| Single numeric column | Box plot |

---

## Portfolio dashboard

```bash
sarathi portfolio                  # opens localhost:7432
sarathi portfolio --port 8080      # custom port
sarathi portfolio --add ./other-project/   # include extra folders
```

The dashboard shows all registered projects with their milestones, last generation time, output status (HTML / PDF / PPTX), and links to open presentations directly in the browser.

---

## Project structure

```
my-project/
├── project.json          # name, description, model (auto-created)
├── data/                 # CSV, JSON, JSONL, TSV
├── plots/                # PNG, JPG, SVG, WebP
├── notes/                # Markdown, TXT, logs, RST
├── .sarathi/
│   ├── timeline.jsonl    # append-only event log
│   ├── config.json       # theme, model, domain override
│   ├── outline.json      # editable JSON outline (--edit-outline)
│   └── viz/              # pre-rendered chart PNGs
└── output/
    ├── presentation.html
    ├── presentation.pdf
    └── presentation.pptx
```

---

## Supported file types

| Type | Extensions | Notes |
|---|---|---|
| Image | `.png` `.jpg` `.jpeg` `.gif` `.webp` | Resized to max 1024 px |
| SVG | `.svg` | Embedded as data URI |
| Data | `.csv` `.json` `.jsonl` `.tsv` | CSVs → auto-charted; capped at 150 rows |
| Text | `.md` `.txt` `.log` `.rst` | Capped at 8000 chars |
| Code | `.py` `.sh` `.bash` `.ipynb` `.r` `.sql` | Capped at 8000 chars |

---

## Prerequisites

- [Ollama](https://ollama.com) running locally (`ollama serve`)
- Claude via Ollama: `ollama launch claude --model kimi-k2.5:cloud`
- Chromium for PDF export: `playwright install chromium`
