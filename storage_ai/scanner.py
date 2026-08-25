"""Filesystem walker that collects per-file metadata for analysis.

Only metadata is read here (stat calls) -- no file contents -- so a scan of
a large tree is fast. Hashing (needed only for duplicate detection) happens
separately in hashing.py / duplicates.py on the much smaller candidate set.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

from storage_ai.config import DEFAULT_EXCLUDES, LINUX_VIRTUAL_FS_ROOTS
from storage_ai.exceptions import ScanCancelled
from storage_ai.models import FileRecord

CancelCheck = Callable[[], bool]


def should_prune_dir(current_root: str, dirname: str, exclude_names: set[str]) -> bool:
    if dirname in exclude_names:
        return True
    return os.path.join(current_root, dirname) in LINUX_VIRTUAL_FS_ROOTS


def _check_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ScanCancelled()


def count_files(
    root: str | Path,
    excludes: set[str] | None = None,
    cancel_check: CancelCheck | None = None,
) -> int:
    """A fast, stat-free pass that counts what `scan_directory` will
    actually process (same pruning rules, same symlink skip) -- used to
    give the real scan a known total to report percentage/ETA against,
    without trusting a possibly-stale count from a previous scan."""
    root = Path(root)
    exclude_names = DEFAULT_EXCLUDES if excludes is None else excludes
    total = 0

    for current_root, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
        _check_cancelled(cancel_check)
        dirnames[:] = [d for d in dirnames if not should_prune_dir(current_root, d, exclude_names)]
        current_path = Path(current_root)
        for filename in filenames:
            if not (current_path / filename).is_symlink():
                total += 1

    return total


def scan_directory(
    root: str | Path,
    excludes: set[str] | None = None,
    on_progress: Callable[[int], None] | None = None,
    cancel_check: CancelCheck | None = None,
    progress_interval: int = 50,
) -> list[FileRecord]:
    """Walk `root` and return metadata for every regular file found.

    Symlinks and unreadable entries are skipped rather than raising, since a
    real user directory almost always contains at least one permission-denied
    or broken-link entry. `on_progress`, if given, is called with the running
    scanned-count every `progress_interval` files (and once more at the end)
    -- not on every single file, to keep cross-thread signal traffic modest
    on a scan of hundreds of thousands of files.
    """
    root = Path(root)
    exclude_names = DEFAULT_EXCLUDES if excludes is None else excludes
    records: list[FileRecord] = []
    scanned = 0

    for current_root, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
        _check_cancelled(cancel_check)
        dirnames[:] = [d for d in dirnames if not should_prune_dir(current_root, d, exclude_names)]
        current_path = Path(current_root)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            depth = 0

        for filename in filenames:
            _check_cancelled(cancel_check)
            file_path = current_path / filename
            try:
                if file_path.is_symlink():
                    continue
                stat_result = file_path.stat()
            except (OSError, ValueError):
                continue

            records.append(
                FileRecord(
                    path=str(file_path),
                    size=stat_result.st_size,
                    extension=file_path.suffix.lower(),
                    created_time=stat_result.st_ctime,
                    modified_time=stat_result.st_mtime,
                    accessed_time=stat_result.st_atime,
                    depth=depth,
                )
            )
            scanned += 1
            if on_progress and scanned % progress_interval == 0:
                on_progress(scanned)

    if on_progress:
        on_progress(scanned)
    return records


def iter_directory(
    root: str | Path,
    excludes: set[str] | None = None,
) -> Iterator[FileRecord]:
    """Generator variant of `scan_directory` for callers that want to stream
    results (e.g. a GUI worker updating a progress bar per file) instead of
    waiting for the whole tree to finish.
    """
    root = Path(root)
    exclude_names = DEFAULT_EXCLUDES if excludes is None else excludes

    for current_root, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if not should_prune_dir(current_root, d, exclude_names)]
        current_path = Path(current_root)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            depth = 0

        for filename in filenames:
            file_path = current_path / filename
            try:
                if file_path.is_symlink():
                    continue
                stat_result = file_path.stat()
            except (OSError, ValueError):
                continue

            yield FileRecord(
                path=str(file_path),
                size=stat_result.st_size,
                extension=file_path.suffix.lower(),
                created_time=stat_result.st_ctime,
                modified_time=stat_result.st_mtime,
                accessed_time=stat_result.st_atime,
                depth=depth,
            )
