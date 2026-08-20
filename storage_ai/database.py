"""SQLite persistence for scan snapshots and the action log.

Snapshots accumulate across repeated scans of the same root and are what
prediction.py uses for a real time-series forecast once enough history
exists. The action log is an audit trail of every archive/delete the app
performed, kept for transparency even though the underlying operations are
themselves recoverable (trash / archive folder, never a hard delete).
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from storage_ai.config import APP_DIR, DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_path TEXT NOT NULL,
    taken_at REAL NOT NULL,
    total_size INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    free_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS extension_breakdown (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    extension TEXT NOT NULL,
    total_size INTEGER NOT NULL,
    file_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at REAL NOT NULL,
    action_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_root ON snapshots(root_path, taken_at);
"""


@contextmanager
def connect(db_path: str | Path = DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_snapshot(
    root_path: str,
    total_size: int,
    file_count: int,
    free_bytes: int,
    extension_totals: dict[str, tuple[int, int]],
    db_path: str | Path = DB_PATH,
    taken_at: float | None = None,
) -> int:
    taken_at = time.time() if taken_at is None else taken_at
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO snapshots (root_path, taken_at, total_size, file_count, free_bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            (root_path, taken_at, total_size, file_count, free_bytes),
        )
        snapshot_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO extension_breakdown (snapshot_id, extension, total_size, file_count) "
            "VALUES (?, ?, ?, ?)",
            [
                (snapshot_id, ext, size, count)
                for ext, (size, count) in extension_totals.items()
            ],
        )
        return snapshot_id


def get_snapshots(root_path: str, db_path: str | Path = DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT taken_at, total_size, file_count, free_bytes FROM snapshots "
            "WHERE root_path = ? ORDER BY taken_at ASC",
            (root_path,),
        ).fetchall()
    return [
        {"taken_at": r[0], "total_size": r[1], "file_count": r[2], "free_bytes": r[3]}
        for r in rows
    ]


def log_action(
    action_type: str,
    path: str,
    size: int,
    detail: str = "",
    db_path: str | Path = DB_PATH,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO actions (taken_at, action_type, path, size, detail) VALUES (?, ?, ?, ?, ?)",
            (time.time(), action_type, path, size, detail),
        )


def get_actions(db_path: str | Path = DB_PATH, limit: int = 200) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT taken_at, action_type, path, size, detail FROM actions "
            "ORDER BY taken_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"taken_at": r[0], "action_type": r[1], "path": r[2], "size": r[3], "detail": r[4]}
        for r in rows
    ]
