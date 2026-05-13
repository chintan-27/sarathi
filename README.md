# Sarathi

Sarathi (Sanskrit: *the charioteer who guides*) is a CLI project companion that watches your work as it evolves, tracks milestones, and automatically generates polished **Reveal.js HTML + PPTX + PDF presentations** using a local LLM via Ollama.

Works across three project types — ML experiments, software development, and data analysis — with a narrative style tailored to each.

---

## Install

```bash
pipx install git+https://github.com/chintan-27/sarathi.git
sarathi setup
```

`sarathi setup` detects your hardware, recommends models for your RAM, pulls your chosen model, and installs Playwright for PDF export.

---

## Using Claude models via Ollama

Sarathi uses Ollama's Anthropic-compatible API — so you get Claude-quality output running entirely on your own machine.

```bash
# Recommended: launch Claude Code through Ollama
ollama launch claude --model kimi-k2.5:cloud

# Then use Sarathi normally — it auto-connects
sarathi join my-project/
```

Or set env vars manually and use any model:

```bash
export ANTHROPIC_BASE_URL=http://localhost:11434
export ANTHROPIC_AUTH_TOKEN=ollama
sarathi track my-project/ --model qwen3.5
```

**Recommended models:**

| Model | Notes |
|---|---|
| `kimi-k2.5:cloud` | Best overall — cloud-routed, no local RAM needed |
| `qwen3.5` | Fast local 8B, great structured output |
| `glm-5:cloud` | Strong reasoning, good for data analysis |
| `llama3.2-vision` | Best for image-heavy projects |

---

## Quickstart

### New project

```bash
sarathi init "bert-vs-gpt" "Comparing BERT and GPT on IMDB sentiment"
cp results/*.png  bert-vs-gpt/plots/
cp metrics.csv    bert-vs-gpt/data/
sarathi track bert-vs-gpt/           # watches for changes, regenerates automatically
```

### Existing project

```bash
sarathi join my-existing-project/    # reads git history + local changes, then generates
```

Sarathi reads the git log, recent commits, uncommitted diffs, and most-changed files to understand where the project stands before building the presentation.

---

## Commands

### Core workflow

| Command | What it does |
|---|---|
| `sarathi setup` | First-time setup: detect hardware, pull models, install Playwright |
| `sarathi init NAME DESC` | Create a new project folder with `data/`, `plots/`, `notes/` |
| `sarathi join FOLDER` | Join an existing project — reads git history and local changes as context |
| `sarathi track FOLDER` | Watch a folder and regenerate on every file change |
| `sarathi make FOLDER` | Generate once and exit (no watching) |
| `sarathi mark FOLDER --name "label"` | Plant a named milestone in the timeline |
| `sarathi log FOLDER` | Print the full project timeline — events, checkpoints, milestones |
| `sarathi status FOLDER` | Show model, theme, last generation time, files changed since then |
| `sarathi diff FOLDER --from M1 --to M2` | Generate a "what changed" presentation between two milestones |

### Output & utilities

| Command | What it does |
|---|---|
| `sarathi portfolio` | Launch a project dashboard at `localhost:7432` |
| `sarathi open FOLDER` | Open `output/presentation.html` in the browser |
| `sarathi export FOLDER --format html\|pdf\|zip` | Re-export without re-generating |
| `sarathi theme FOLDER --set THEME` | Set slide theme: `dark-gradient`, `dracula`, `light`, `minimal` |
| `sarathi models` | List Ollama models, flag vision-capable ones |
| `sarathi pull MODEL` | Download an Ollama model |
| `sarathi clean FOLDER` | Wipe `output/` and `.sarathi/viz/` cache |

### Sanskrit aliases

Every command has a Sanskrit alias — both work identically.

| English | Sanskrit | Meaning |
|---|---|---|
| `init` | `arambh` | beginning |
| `track` | `yatra` | journey |
| `make` | `bana` | build |
| `mark` | `padav` | waypoint |
| `log` | `safar` | travelogue |
| `status` | `haal` | current state |
| `open` | `dekh` | look/see |
| `diff` | `antar` | difference |

### Key flags

| Flag | Command | Effect |
|---|---|---|
| `--model MODEL` | `track`, `make`, `join` | Override the Ollama model for this run |
| `--once` | `track`, `join` | Generate once then exit instead of watching |
| `--edit-outline` | `track`, `make` | Save the JSON narrative outline to `.sarathi/outline.json` before rendering — edit it, then re-run without this flag |

---

## How generation works

Sarathi uses a **two-pass pipeline** — the same pattern used by research systems like PPTAgent and ArcDeck:

```
git_context.extract()       → commit history, diffs, hot files (if git repo)
scanner.scan()              → result files: images, CSVs, text, code
viz.process()               → pre-render CSVs to chart PNGs (auto chart selection)
builder._generate_outline() → Pass 1: LLM produces a JSON narrative outline
builder._render_slide()     → Pass 2: one LLM call per slide → Reveal.js HTML
pptx_exporter.to_pptx()    → convert outline + images → .pptx
exporter.to_pdf()           → Playwright → PDF
```

**Domain detection** — Sarathi reads your description and files to pick the right story arc:

| Domain | Narrative arc | Tone |
|---|---|---|
| `ml` | Hypothesis → Experiments → Ablation → Final model | Empirical, methodological |
| `software` | Problem anecdote → Architecture → Solution → Results | Architecture-centric |
| `data` | Key finding first → Supporting evidence → Recommendations | Insight-first, persuasive |

**Automatic chart selection** from CSVs:

| Data shape | Chart |
|---|---|
| datetime column + numeric | Line chart |
| 2 numeric, high cardinality | Scatter plot |
| 3+ numeric columns | Correlation heatmap |
| Categorical + numeric | Horizontal bar chart |
| Part-to-whole | Stacked bar |
| Single numeric | Box plot |

---

## Portfolio dashboard

```bash
sarathi portfolio                    # opens localhost:7432
sarathi portfolio --port 8080
sarathi portfolio --add ./other/     # include extra folders
```

Shows all tracked projects with milestones, last generation time, output badges (HTML / PDF / PPTX), and direct links to open presentations.

---

## Project structure

```
my-project/
├── project.json          # name, description, model (auto-created)
├── data/                 # CSV, JSON, JSONL, TSV
├── plots/                # PNG, JPG, SVG, WebP
├── notes/                # Markdown, TXT, logs
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
| Data | `.csv` `.json` `.jsonl` `.tsv` | CSVs auto-charted; capped at 150 rows |
| Text | `.md` `.txt` `.log` `.rst` | Capped at 8000 chars |
| Code | `.py` `.sh` `.bash` `.ipynb` `.r` `.sql` | Capped at 8000 chars |

---

## Prerequisites

- [Ollama](https://ollama.com) running locally
- Claude via Ollama: `ollama launch claude --model kimi-k2.5:cloud`
- Chromium for PDF export: installed automatically by `sarathi setup`
