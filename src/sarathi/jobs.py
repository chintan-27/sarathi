"""Background job queue and tracking for sarathi.

Architecture:
  - queue.json   : pending generation jobs (FIFO)
  - jobs.json    : history of all jobs (running + completed)
  - worker.pid   : PID of the active queue worker process
  - logs/<id>.log: stdout/stderr of each job

Only one generation runs at a time. The worker process drains the
queue sequentially so Ollama RAM is not overloaded.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_CONFIG_DIR = Path.home() / ".config" / "sarathi"
_QUEUE_FILE  = _CONFIG_DIR / "queue.json"
_JOBS_FILE   = _CONFIG_DIR / "jobs.json"
_WORKER_PID  = _CONFIG_DIR / "worker.pid"
_LOGS_DIR    = _CONFIG_DIR / "logs"

_MAX_HISTORY = 100


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    _ensure_dirs()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Queue ─────────────────────────────────────────────────────────────────────

def enqueue(project_path: str, fast: bool = False, model: str | None = None,
            offload: bool = False, label: str = "") -> dict:
    """Add a generation job to the queue. Returns the queued job dict."""
    _ensure_dirs()
    job_id = f"gen-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:21]}"
    job = {
        "id":       job_id,
        "project":  project_path,
        "fast":     fast,
        "model":    model or "",
        "offload":  offload,
        "label":    label,
        "queued_at": datetime.now().isoformat(timespec="seconds"),
        "status":   "queued",
        "log":      str(_LOGS_DIR / f"{job_id}.log"),
    }
    queue = _read_json(_QUEUE_FILE, [])
    queue.append(job)
    _write_json(_QUEUE_FILE, queue)
    _append_job(job)
    return job


def dequeue() -> dict | None:
    """Remove and return the next pending job from the queue."""
    queue = _read_json(_QUEUE_FILE, [])
    pending = [j for j in queue if j.get("status") == "queued"]
    if not pending:
        return None
    job = pending[0]
    # Mark as running in queue file
    for j in queue:
        if j["id"] == job["id"]:
            j["status"] = "running"
            j["started"] = datetime.now().isoformat(timespec="seconds")
    _write_json(_QUEUE_FILE, queue)
    return job


def finish_queued(job_id: str, status: str = "done") -> None:
    """Remove a completed job from the queue."""
    queue = _read_json(_QUEUE_FILE, [])
    queue = [j for j in queue if j["id"] != job_id]
    _write_json(_QUEUE_FILE, queue)
    update_job(job_id, status=status)


def get_queue() -> list[dict]:
    """Return all pending + running jobs in the queue."""
    return _read_json(_QUEUE_FILE, [])


def queue_length() -> int:
    return len([j for j in get_queue() if j.get("status") == "queued"])


# ── Job history ───────────────────────────────────────────────────────────────

def _append_job(job: dict) -> None:
    jobs = _read_json(_JOBS_FILE, [])
    jobs.append(job)
    if len(jobs) > _MAX_HISTORY:
        jobs = jobs[-_MAX_HISTORY:]
    _write_json(_JOBS_FILE, jobs)


def update_job(job_id: str, **fields: Any) -> None:
    jobs = _read_json(_JOBS_FILE, [])
    for j in jobs:
        if j["id"] == job_id:
            j.update(fields)
            break
    _write_json(_JOBS_FILE, jobs)


def get_all_jobs(limit: int = 50) -> list[dict]:
    return _read_json(_JOBS_FILE, [])[-limit:]


def get_recent_jobs(since_iso: str = "", limit: int = 20) -> list[dict]:
    jobs = _read_json(_JOBS_FILE, [])
    if since_iso:
        jobs = [j for j in jobs if j.get("queued_at", "") >= since_iso]
    return jobs[-limit:]


# ── Worker process ────────────────────────────────────────────────────────────

def is_worker_running() -> bool:
    """Return True if the queue worker process is alive."""
    if not _WORKER_PID.exists():
        return False
    try:
        pid = int(_WORKER_PID.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        _WORKER_PID.unlink(missing_ok=True)
        return False


def _write_worker_pid(pid: int) -> None:
    _ensure_dirs()
    _WORKER_PID.write_text(str(pid))


def clear_worker_pid() -> None:
    _WORKER_PID.unlink(missing_ok=True)


def start_worker_if_idle() -> bool:
    """Spawn the queue worker if it's not already running.

    Returns True if a new worker was started.
    """
    if is_worker_running():
        return False
    if queue_length() == 0:
        return False

    exe = shutil.which("sarathi") or sys.argv[0]
    log_path = str(_LOGS_DIR / f"worker-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log")
    _ensure_dirs()
    log_fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [exe, "_worker"],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    _write_worker_pid(proc.pid)
    return True


# ── Reporting ─────────────────────────────────────────────────────────────────

def tail_log(job_id: str, lines: int = 40) -> str:
    for j in get_all_jobs():
        if j["id"] == job_id:
            p = Path(j.get("log", ""))
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
                return "\n".join(text.splitlines()[-lines:])
            return "(no log yet)"
    return f"Job {job_id!r} not found."


def kill_job(job_id: str) -> bool:
    """Send SIGTERM to a running job's process."""
    import signal
    for j in get_all_jobs():
        if j["id"] == job_id:
            pid = j.get("pid", 0)
            if pid:
                try:
                    os.kill(pid, signal.SIGTERM)
                    update_job(job_id, status="interrupted")
                    return True
                except Exception:
                    pass
    return False


def kill_worker() -> bool:
    """Stop the queue worker."""
    import signal
    if not _WORKER_PID.exists():
        return False
    try:
        pid = int(_WORKER_PID.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        _WORKER_PID.unlink(missing_ok=True)
        return True
    except Exception:
        return False
