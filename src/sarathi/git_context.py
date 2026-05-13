from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def is_git_repo(project_dir: Path) -> bool:
    return _run(["git", "rev-parse", "--git-dir"], project_dir) != ""


def extract(project_dir: Path) -> dict | None:
    """Return a structured git context dict, or None if not a git repo."""
    if not is_git_repo(project_dir):
        return None

    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], project_dir)

    # Last 30 commits: hash, date, message
    log_raw = _run([
        "git", "log", "--oneline", "--no-merges",
        "--format=%h|%ad|%s", "--date=short", "-30"
    ], project_dir)
    commits = []
    for line in log_raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0], "date": parts[1], "message": parts[2]})

    # Files changed in the last 30 commits, ranked by frequency
    freq_raw = _run([
        "git", "log", "--no-merges", "--name-only",
        "--format=", "-30"
    ], project_dir)
    freq: dict[str, int] = {}
    for f in freq_raw.splitlines():
        f = f.strip()
        if f:
            freq[f] = freq.get(f, 0) + 1
    hot_files = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]

    # Uncommitted changes (staged + unstaged)
    diff_stat = _run(["git", "diff", "HEAD", "--stat"], project_dir)
    diff_summary = _run(["git", "diff", "HEAD", "--unified=2"], project_dir)
    # Cap diff to avoid flooding context
    if len(diff_summary) > 4000:
        diff_summary = diff_summary[:4000] + "\n... (diff truncated)"

    # Untracked files
    untracked = _run([
        "git", "ls-files", "--others", "--exclude-standard"
    ], project_dir).splitlines()[:20]

    # Last generation or meaningful commit
    first_commit_date = ""
    first_raw = _run(["git", "log", "--format=%ad", "--date=short", "--reverse"], project_dir)
    if first_raw:
        first_commit_date = first_raw.splitlines()[0]

    return {
        "branch":           branch,
        "commits":          commits,
        "hot_files":        hot_files,
        "diff_stat":        diff_stat,
        "diff_summary":     diff_summary,
        "untracked":        untracked,
        "first_commit_date": first_commit_date,
        "total_commits":    len(_run(["git", "rev-list", "--count", "HEAD"],
                                    project_dir).split()) and
                            int(_run(["git", "rev-list", "--count", "HEAD"],
                                     project_dir) or 0),
    }


def format_for_llm(ctx: dict) -> str:
    """Render git context as a compact text block for the LLM planner prompt."""
    lines: list[str] = []

    lines.append(f"Branch: {ctx['branch']}  |  "
                 f"Total commits: {ctx['total_commits']}  |  "
                 f"Project started: {ctx['first_commit_date']}")

    if ctx["commits"]:
        lines.append("\nRecent commits (newest first):")
        for c in ctx["commits"][:15]:
            lines.append(f"  {c['date']}  {c['hash']}  {c['message']}")

    if ctx["hot_files"]:
        lines.append("\nMost actively changed files:")
        for f, n in ctx["hot_files"]:
            lines.append(f"  {f}  ({n} commits)")

    if ctx["diff_stat"]:
        lines.append("\nUncommitted changes (stat):")
        for line in ctx["diff_stat"].splitlines():
            lines.append(f"  {line}")

    if ctx["diff_summary"]:
        lines.append("\nUncommitted diff (excerpt):")
        lines.append(ctx["diff_summary"])

    if ctx["untracked"]:
        lines.append("\nUntracked files:")
        for f in ctx["untracked"]:
            lines.append(f"  {f}")

    return "\n".join(lines)


def print_summary(ctx: dict, console) -> None:
    """Print a human-readable git summary to the Rich console."""
    from rich.table import Table
    from rich import box

    console.print(
        f"[dim][git][/dim] Branch [bold cyan]{ctx['branch']}[/bold cyan]  ·  "
        f"[bold]{ctx['total_commits']}[/bold] commits  ·  "
        f"started [dim]{ctx['first_commit_date']}[/dim]"
    )

    if ctx["commits"]:
        t = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        t.add_column(style="dim", width=10)
        t.add_column(style="dim", width=7)
        t.add_column()
        for c in ctx["commits"][:8]:
            t.add_row(c["date"], c["hash"], c["message"])
        console.print(t)

    if ctx["diff_stat"]:
        console.print(f"[yellow][git] Uncommitted changes:[/yellow]")
        for line in ctx["diff_stat"].splitlines()[:6]:
            console.print(f"  [dim]{line}[/dim]")

    if ctx["untracked"]:
        console.print(
            f"[dim][git] {len(ctx['untracked'])} untracked file(s)[/dim]"
        )
