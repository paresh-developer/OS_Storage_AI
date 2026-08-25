"""Live filesystem event watcher -- cross-platform via the `watchdog`
library (wraps Linux inotify / Windows ReadDirectoryChangesW / macOS
FSEvents).

This alone can tell you a path changed and roughly what kind of change it
was, attributed only to whoever *owns* the file (from stat()) -- it cannot
tell you which OS user actually performed a given operation on a
multi-user system, since inotify/watchdog have no such concept. See
audit_log.py for real per-operation attribution on Linux, which
watcher_service.py correlates in after the fact.
"""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from storage_ai.config import DEFAULT_EXCLUDES
from storage_ai.models import FileEvent
from storage_ai.scanner import should_prune_dir


class LiveWatcherError(Exception):
    """Raised when the OS-level watch mechanism fails to start. Watchdog
    validates each watched path synchronously inside `start()` (it calls
    `inotify_add_watch()`-equivalent setup before spawning its thread,
    specifically so setup failures aren't silently swallowed in a
    background thread) -- this wraps that failure with an actionable
    message instead of a raw OSError."""


def _friendly_start_error(exc: OSError, paths: list[str]) -> str:
    if getattr(exc, "errno", None) == errno.ENOSPC:
        return (
            "Could not start watching: the OS's inotify watch limit was exceeded. "
            "This usually means the folder is very large or deep -- watchdog needs one "
            "watch per subdirectory, and excluded noisy directories (.git, node_modules, "
            ".venv, ...) are already skipped. Try watching a narrower folder, or raise "
            "the limit:\n"
            "  sudo sysctl fs.inotify.max_user_watches=524288"
        )
    return f"Could not start watching {', '.join(paths)}: {exc}"


def _resolve_owner(path: str) -> tuple[int | None, str | None]:
    try:
        stat_result = os.stat(path)
    except OSError:
        return None, None
    uid = stat_result.st_uid
    username = None
    try:
        import pwd

        username = pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        pass
    return uid, username


def _file_size(path: str) -> int | None:
    try:
        return os.stat(path).st_size
    except OSError:
        return None


def iter_watchable_dirs(root: str, exclude_names: set[str]):
    """Yields `root` and every non-pruned, accessible subdirectory under
    it -- mirrors scanner.py's exclusion logic (noisy directories like
    .git/node_modules/.venv, plus true virtual filesystems like /proc on
    Linux) so live monitoring never wastes inotify watches on them or
    chokes trying to watch /proc's constantly-changing, ephemeral,
    per-process entries.

    Directories the current user can't read are silently skipped (same as
    os.walk's default behavior, via onerror=lambda e: None below) rather
    than treated as fatal -- important for watching something broad like
    "/" as a non-root user, where plenty of subtrees are legitimately
    off-limits and shouldn't abort monitoring everything else.
    """
    yield root
    for current_root, dirnames, _filenames in os.walk(root, topdown=True, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if not should_prune_dir(current_root, d, exclude_names)]
        for d in dirnames:
            yield os.path.join(current_root, d)


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        on_event: Callable[[FileEvent], None],
        observer: Observer,
        exclude_names: set[str],
    ) -> None:
        self._on_event = on_event
        self._observer = observer
        self._exclude_names = exclude_names

    def _emit(self, event_type: str, path: str) -> None:
        if event_type == "deleted":
            uid, username, size = None, None, None
        else:
            uid, username = _resolve_owner(path)
            size = _file_size(path)
        self._on_event(
            FileEvent(
                timestamp=time.time(),
                path=path,
                event_type=event_type,
                size=size,
                uid=uid,
                username=username,
                attribution_source="stat" if username else "unknown",
            )
        )

    def _extend_coverage(self, new_dir: str) -> None:
        """A watch on a directory only covers that directory itself, not
        anything created inside it later -- so a newly created subdirectory
        needs its own watch registered on the fly to keep recursive
        coverage, the same exclusion rules applied as at startup."""
        if os.path.basename(new_dir) in self._exclude_names:
            return
        for directory in iter_watchable_dirs(new_dir, self._exclude_names):
            try:
                self._observer.schedule(self, directory, recursive=False)
            except OSError:
                continue  # e.g. permission denied, or it vanished already -- skip, don't crash monitoring

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            self._extend_coverage(event.src_path)
            return
        self._emit("created", event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._emit("modified", event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._emit("deleted", event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            self._extend_coverage(event.dest_path)
            return
        self._emit("deleted", event.src_path)
        self._emit("created", event.dest_path)


class LiveWatcher:
    """Watches one or more directory trees, calling `on_event` for every
    create/modify/delete/move. Runs its own background thread (via
    watchdog's Observer) -- call `start()`/`stop()` to control it.

    Each watchable directory gets its own individual (non-recursive) watch,
    set up via `iter_watchable_dirs` rather than one `recursive=True` watch
    on the root -- this is what lets noisy/huge directories (.git,
    node_modules, .venv) and true virtual filesystems (/proc, /sys, /dev,
    /run) be excluded, and what lets a permission-denied subtree be skipped
    instead of aborting the whole watch (`recursive=True` on the raw root
    would abort entirely the moment it reached even one such directory --
    exactly what made watching "/" as a non-root user fail outright before
    this). The `_Handler` dynamically extends coverage to newly created
    subdirectories so this doesn't lose recursive coverage over time.

    `start()` can still fail (see LiveWatcherError) -- most commonly Linux's
    inotify watch-count limit on a very large tree, or a rare race where a
    directory that was accessible during setup vanished by the time the
    watch actually starts. When it does, the observer's own thread never
    actually starts, so `stop()` is a safe no-op in that case rather than
    raising trying to join a thread that was never running.
    """

    def __init__(
        self,
        paths: list[str],
        on_event: Callable[[FileEvent], None],
        excludes: set[str] | None = None,
    ) -> None:
        self._paths = paths
        self._exclude_names = DEFAULT_EXCLUDES if excludes is None else excludes
        self._observer = Observer()
        self._started = False
        handler = _Handler(on_event, self._observer, self._exclude_names)
        for root in paths:
            for directory in iter_watchable_dirs(root, self._exclude_names):
                try:
                    self._observer.schedule(handler, directory, recursive=False)
                except OSError:
                    continue

    def start(self) -> None:
        try:
            self._observer.start()
        except OSError as exc:
            raise LiveWatcherError(_friendly_start_error(exc, self._paths)) from exc
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._started = False

    @property
    def is_alive(self) -> bool:
        return self._started and self._observer.is_alive()
