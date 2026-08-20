"""Filesystem walker that collects per-file metadata for analysis.

Only metadata is read here (stat calls) -- no file contents -- so a scan of
a large tree is fast. Hashing (needed only for duplicate detection) happens
separately in hashing.py / duplicates.py on the much smaller candidate set.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

from storage_ai.config import DEFAULT_EXCLUDES
from storage_ai.models import FileRecord

ProgressCallback = Callable[[int, str], None]


def scan_directory(
    root: str | Path,
    excludes: set[str] | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[FileRecord]:
    """Walk `root` and return metadata for every regular file found.

    Symlinks and unreadable entries are skipped rather than raising, since a
    real user directory almost always contains at least one permission-denied
    or broken-link entry.
    """
    root = Path(root)
    exclude_names = DEFAULT_EXCLUDES if excludes is None else excludes
    records: list[FileRecord] = []
    scanned = 0

    for current_root, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in exclude_names]
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
            if on_progress and scanned % 500 == 0:
                on_progress(scanned, str(file_path))

    if on_progress:
        on_progress(scanned, "done")
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
        dirnames[:] = [d for d in dirnames if d not in exclude_names]
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
