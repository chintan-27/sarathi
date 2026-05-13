from __future__ import annotations

from pathlib import Path
from threading import Timer
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SKIP_PARTS = {"output", ".git", "__pycache__", ".sarathi"}


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, generate_fn: Callable, project_dir: Path,
                 debounce: float = 3.0):
        super().__init__()
        self._generate = generate_fn
        self._project_dir = project_dir
        self._debounce = debounce
        self._timer: Timer | None = None
        self._changed: set[str] = set()

    def on_any_event(self, event):
        if event.is_directory:
            return
        src = Path(event.src_path)
        if src.name.startswith("."):
            return
        if any(part in SKIP_PARTS for part in src.parts):
            return
        try:
            self._changed.add(str(src.relative_to(self._project_dir)))
        except ValueError:
            self._changed.add(src.name)
        self._reset_timer()

    def _reset_timer(self):
        if self._timer:
            self._timer.cancel()
        self._timer = Timer(self._debounce, self._fire)
        self._timer.start()

    def _fire(self):
        from . import tracker as trk
        changed = list(self._changed)
        self._changed.clear()
        for f in changed:
            trk.log_event(self._project_dir, "file_added", file=f)
        self._generate()


def watch(project_dir: Path, generate_fn: Callable, debounce: float = 3.0) -> None:
    handler = _ChangeHandler(generate_fn, project_dir, debounce)
    observer = Observer()
    observer.schedule(handler, str(project_dir), recursive=True)
    observer.start()
    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
