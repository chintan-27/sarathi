# Sarathi

Sarathi (Sanskrit: *the charioteer who guides*) is a local CLI **project companion** — it watches your work as it evolves, tracks milestones, versions your presentations automatically, and generates polished **Reveal.js HTML + PPTX + PDF** using a local LLM via Ollama.

Works across ML experiments, software development, and data analysis projects, with a narrative arc and tone adapted to each domain.

---

## Install

```bash
pipx install git+https://github.com/chintan-27/sarathi.git
sarathi setup
```

`sarathi setup` detects your hardware, benchmarks local models, assigns Planner / Coder / Vision / Fast roles, and installs Playwright for PDF export.

---

## How Sarathi uses Ollama

Sarathi talks to Ollama's local API. No Anthropic account or API key needed — everything runs on your machine.

```bash
ollama serve          # start Ollama (keep running)
sarathi track my-project/
```

**Recommended models:**

| Role | Model | RAM |
|---|---|---|
| Planner (outline) | `gemma3:4b` | ~3 GB |
| Coder (slides) | `qwen2.5-coder:7b` | ~5 GB |
| Vision (images) | `llama3.2-vision` | ~8 GB |
| Fast (quick regen) | `qwen2.5:3b` | ~2 GB |

Override per-run: `sarathi track my-project/ --model mistral:7b`

---

## The Complete Flow

### 0. First-time setup (once)

```bash
sarathi setup
```

Detects installed models, benchmarks each, assigns roles, writes `~/.config/sarathi/config.json`.

---

### 1. Start a new project

```bash
sarathi init
# or: sarathi arambh
```

Runs an interactive wizard that collects:
- Name, one-line description, goal (longer — shown in portfolio)
- Domain: ML / Software / Data / Auto-detect
- Tags (comma-separated keywords)
- Status: Active / Planning / On Hold / Shipped
- Repository URL, related link (paper, dataset, Notion page)
- Team / collaborators
- Model choice
- Optional day-0 milestone (snapshots starting state)

Creates the folder with `data/`, `plots/`, `notes/`, `output/` and registers it in the portfolio.

**Joining an existing project:**

```bash
sarathi join my-existing-project/
# or: sarathi join my-existing-project/ --once
```

Same wizard, auto-detects the git remote URL. Reads git log, recent commits, uncommitted diffs, and most-changed files as context for the first generation.

---

### 2. Active work session — the core loop

```bash
sarathi track my-project/
# or: sarathi yatra my-project/
```

This is the main command. It:
1. **Generates immediately** — scans files, runs two-pass LLM (Planner → per-slide Coder), writes `output/presentation.html`, `.pdf`, `.pptx`
2. **Watches for changes** — any file save re-triggers generation after a 3-second debounce
3. **Keeps the portfolio live** — writes a PID file so the dashboard shows "2 watchers active"

While this runs in one terminal, work normally in another. Every result file you save triggers a new deck automatically.

**One-shot (no watching):**
```bash
sarathi make my-project/ --once
sarathi make my-project/ --once --fast   # single-pass, ~30s vs ~2 min
```

---

### 3. Mark milestones → version the presentation

```bash
sarathi mark my-project/ --name "baseline model done"
# or: sarathi padav my-project/ --name "v1 shipped"
```

Each milestone:
- Hashes every file at that moment (enables future diffs)
- **Automatically snapshots** `output/presentation.*` → `output/v1-baseline-model-done/`
- Appends to `.sarathi/timeline.jsonl`

The next generation after a milestone automatically adds a **recap slide** — "Since v1: What Changed" — showing new files, commits, and days elapsed since the previous milestone.

**Output versioning structure:**
```
output/
  presentation.html         ← always the latest
  presentation.pdf
  presentation.pptx
  v1-baseline-model-done/   ← snapshotted at milestone
    presentation.html
    presentation.pdf
    presentation.pptx
    meta.json
  v2-v1-shipped/            ← next milestone snapshot
    ...
```

---

### 4. Check what's happening

```bash
sarathi status my-project/
# or: sarathi haal my-project/
```

Shows: last generated timestamp, files changed since then, current milestone count, model assignments.

```bash
sarathi log my-project/
# or: sarathi safar my-project/
```

Prints the full timeline: init, file changes, milestones (★), generations (⚡), checkpoints.

---

### 5. End of session

```bash
sarathi viraam
```

Sanskrit for "pause / rest". Marks a named milestone across all active projects, then regenerates all projects that have file changes since their last deck. Use this before stepping away.

---

### 6. Picking up after a break

```bash
sarathi update
# or: sarathi navakar
```

Scans all registered projects, finds any with files changed since last generation, regenerates them sequentially. Good for Monday morning.

---

### 7. Portfolio dashboard

```bash
sarathi portfolio
# opens http://localhost:7432
```

The dashboard is always live — polls every 5 seconds. Shows:

**Top bar**: Ollama status (model loaded, RAM used), active watcher count, generation-in-progress indicator

**Bento grid**: all projects as colored editorial cards — status badge, tags, evolution level (Seed → Active → Story-Rich → Presentation-Ready), KPIs, 14-day sparkline, narrative sentence, git pulse, output badges (HTML / PDF / PPTX)

**Click any card → Detail page**:
- 52-week GitHub-style activity heatmap
- Narrative event feed (written as sentences, not log lines)
- Generation history table (fastest row highlighted, model speed chart)
- Git: recent commits with +/- stats, top-changed files, weekly sparkline
- File browser grouped by type (Images / Data / Code / Text)
- CSV data insights: shape, columns, mean ± std per numeric column
- **Version history table**: v1, v2, v3... with milestone label, date, slide count, model, duration, open link
- Milestone vertical timeline with days-between gaps
- Model role cards (Planner / Coder / Vision / Fast)

**Personality layer**: achievement badges (First Generation, Speed Demon, Archivist…), daily "This Week" Wrapped strip, rotating domain-relevant quote

---

### 8. Compare milestones

```bash
sarathi diff my-project/ --from "baseline model done" --to "v1 shipped"
# or: sarathi antar my-project/ ...
```

Reconstructs file state at both milestones, generates a diff-narrative presentation showing what changed.

---

### 9. Share output

```bash
sarathi open my-project/                    # open latest HTML in browser
sarathi export my-project/ --format pdf     # re-export PDF without LLM call
sarathi export my-project/ --format zip     # HTML + PDF + PPTX as archive
```

---

## Daily rhythm

```
Morning
  sarathi update                     ← regenerate anything that changed overnight

During work (one terminal)
  sarathi track my-project/          ← watches + auto-regenerates on every file save

Milestone reached
  sarathi mark my-project/ --name "experiment 3 done"
  # → archives output/v2-experiment-3-done/
  # → next generation includes a recap slide

End of day
  sarathi viraam                     ← mark + regenerate all → Ctrl-C watchers
  sarathi portfolio                  ← review what Sarathi built today
```

---

## Commands

### Core

| Command | Alias | What it does |
|---|---|---|
| `sarathi setup` | — | First-time: benchmark models, assign roles |
| `sarathi init` | `arambh` | Interactive wizard → create new project |
| `sarathi join FOLDER` | — | Adopt existing project with wizard |
| `sarathi track FOLDER` | `yatra` | Watch + auto-regenerate on file change |
| `sarathi make FOLDER --once` | `bana` | Generate once and exit |
| `sarathi mark FOLDER --name X` | `padav` | Mark milestone + snapshot presentation as vN |
| `sarathi log FOLDER` | `safar` | Print full project timeline |
| `sarathi status FOLDER` | `haal` | Current state: pending files, last gen, models |
| `sarathi update` | `navakar` | Regenerate all projects with pending changes |
| `sarathi viraam` | — | End-of-session: mark milestone + regenerate all |

### Output & utilities

| Command | Alias | What it does |
|---|---|---|
| `sarathi portfolio` | — | Launch dashboard at `localhost:7432` |
| `sarathi open FOLDER` | `dekh` | Open `output/presentation.html` in browser |
| `sarathi diff FOLDER` | `antar` | Generate diff presentation between two milestones |
| `sarathi export FOLDER` | — | Re-export HTML / PDF / ZIP without regenerating |
| `sarathi theme FOLDER` | — | Set slide theme |
| `sarathi models` | — | List Ollama models, flag vision-capable ones |
| `sarathi pull MODEL` | — | Download an Ollama model |
| `sarathi clean FOLDER` | — | Wipe `output/` and `.sarathi/viz/` cache |

### Key flags

| Flag | Applies to | Effect |
|---|---|---|
| `--once` | `track`, `join` | Generate once and exit, no watching |
| `--fast` | `track`, `make`, `join` | Single-pass generation (~30s, lower quality) |
| `--model MODEL` | `track`, `make`, `join` | Override model for this run |
| `--edit-outline` | `track`, `make` | Pause after Pass 1, let you edit JSON outline |
| `--verbose` | `track`, `make` | Print every prompt and raw LLM response |

---

## How generation works

**Two-pass pipeline** (default):

```
git_context.extract()        → commit history, diffs, hot files
scanner.scan()               → images, CSVs, text, code, notebooks
viz.process()                → pre-render CSVs → chart PNGs
builder._generate_outline()  → Pass 1: Planner LLM → JSON narrative outline
builder._render_slide()      → Pass 2: Coder LLM → one <section> per slide
pptx_exporter.to_pptx()     → outline + images → .pptx
exporter.to_pdf()            → Playwright → .pdf
```

**Versioned generation** (when a new milestone was marked since last run):

Same pipeline, but the Planner receives a `<VersionDelta>` block describing new files, modified files, and commits since the previous milestone. Slide 2 becomes a recap: "Since v1: What Changed".

**Domain arcs:**

| Domain | Narrative | Tone |
|---|---|---|
| `ml` | Hypothesis → Experiments → Ablation → Final model | Empirical |
| `software` | Problem → Architecture → Solution → Results | Architecture-centric |
| `data` | Key finding first → Evidence → Recommendations | Insight-first |

**Slide type variety** — every deck must include at least 4 different types:

`metric_callout` · `chart` · `image` · `code` · `table` · `comparison` · `context` · `takeaways` · `next_steps`

**Auto chart selection** from CSVs:

| Data shape | Chart |
|---|---|
| Datetime column | Line chart |
| 2 high-cardinality numeric | Scatter |
| 3+ numeric | Correlation heatmap |
| Categorical + numeric | Horizontal bar |
| Single numeric, > 500 rows | Histogram |

---

## Project structure

```
my-project/
├── project.json            # name, description, goal, domain, tags, status, team, repo_url
├── data/                   # CSV, JSON, JSONL, TSV
├── plots/                  # PNG, JPG, SVG, WebP
├── notes/                  # Markdown, TXT, logs
├── .sarathi/
│   ├── timeline.jsonl      # append-only event log
│   ├── config.json         # theme, model, domain override
│   ├── outline.json        # editable JSON outline (--edit-outline)
│   ├── watcher.pid         # PID of active sarathi track process
│   ├── status.json         # current generation state (polled by portfolio)
│   └── viz/                # pre-rendered chart PNGs
└── output/
    ├── presentation.html   ← always latest
    ├── presentation.pdf
    ├── presentation.pptx
    ├── v1-baseline-done/   ← snapshotted at first milestone
    │   ├── presentation.html
    │   ├── presentation.pdf
    │   ├── presentation.pptx
    │   └── meta.json
    └── v2-v1-shipped/      ← second milestone snapshot
        └── ...
```

---

## Supported file types

| Type | Extensions | Notes |
|---|---|---|
| Image | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.tiff` | Resized to max 1280 px |
| SVG | `.svg` | Embedded as data URI |
| Data | `.csv` `.json` `.jsonl` `.tsv` | CSVs auto-charted, capped at 200 rows |
| Text | `.md` `.txt` `.log` `.rst` `.out` `.err` | Capped at 10 000 chars |
| Code | `.py` `.sh` `.bash` `.r` `.sql` `.js` `.ts` `.go` `.rs` `.java` `.cpp` `.c` | Capped at 10 000 chars |
| Notebook | `.ipynb` | Extracts cells + outputs + embedded charts |

---

## Prerequisites

- [Ollama](https://ollama.com) running locally (`ollama serve`)
- Python 3.11+
- Chromium for PDF export: installed automatically by `sarathi setup`
