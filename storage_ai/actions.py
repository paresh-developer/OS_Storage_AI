"""Cleanup actions the GUI can trigger. Nothing here permanently deletes data:

- `trash_file` sends to the OS trash/recycle bin (via send2trash), so any
  action taken on the strength of a heuristic or model score is reversible.
- `archive_file` moves the file into a local archive folder instead,
  preserving its original relative path, for files the user wants out of
  the way but not gone.

Every call is logged to the actions table for auditability.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from send2trash import send2trash

from storage_ai.config import ARCHIVE_DIR
from storage_ai.database import log_action


def trash_file(path: str) -> None:
    file_path = Path(path)
    size = file_path.stat().st_size if file_path.exists() else 0
    send2trash(str(file_path))
    log_action("trash", str(file_path), size)


def archive_file(path: str, root: str) -> str:
    """Move `path` into ARCHIVE_DIR, preserving its position relative to
    `root` so multiple archived files don't collide by filename. Returns the
    new location."""
    file_path = Path(path)
    root_path = Path(root)
    size = file_path.stat().st_size if file_path.exists() else 0

    try:
        relative = file_path.relative_to(root_path)
    except ValueError:
        relative = Path(file_path.name)

    timestamp = time.strftime("%Y-%m-%d")
    destination = ARCHIVE_DIR / timestamp / relative
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        destination = destination.with_name(f"{destination.stem}_{int(time.time())}{destination.suffix}")

    shutil.move(str(file_path), str(destination))
    log_action("archive", str(file_path), size, detail=str(destination))
    return str(destination)
