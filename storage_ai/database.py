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

CREATE TABLE IF NOT EXISTS file_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    path TEXT NOT NULL,
    event_type TEXT NOT NULL,
    size INTEGER,
    uid INTEGER,
    username TEXT,
    attribution_source TEXT NOT NULL,
    pid INTEGER,
    process_name TEXT
);

CREATE TABLE IF NOT EXISTS activity_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    alert_type TEXT NOT NULL,
    username TEXT,
    detail TEXT NOT NULL,
    severity TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_root ON snapshots(root_path, taken_at);
CREATE INDEX IF NOT EXISTS idx_file_events_timestamp ON file_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_file_events_path ON file_events(path, timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_alerts_timestamp ON activity_alerts(timestamp);
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


def get_recent_roots(limit: int = 10, db_path: str | Path = DB_PATH) -> list[dict]:
    """The most recently scanned distinct folders, most-recent first, each
    with the stats from *its own* latest snapshot -- backs the "Open
    Recent" menu."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.root_path, s.taken_at, s.total_size, s.file_count
            FROM snapshots s
            WHERE s.taken_at = (SELECT MAX(taken_at) FROM snapshots WHERE root_path = s.root_path)
            ORDER BY s.taken_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {"root_path": r[0], "taken_at": r[1], "total_size": r[2], "file_count": r[3]}
        for r in rows
    ]


def clear_scan_history(db_path: str | Path = DB_PATH) -> None:
    """Clears the recent-folders list and the growth-forecast history
    (snapshots + their extension breakdowns). Deliberately leaves the
    `actions` audit log untouched -- that's a record of what was actually
    trashed/archived, a different kind of history than "which folders have
    I scanned."""
    with connect(db_path) as conn:
        conn.execute("DELETE FROM extension_breakdown")
        conn.execute("DELETE FROM snapshots")


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


def record_file_event(event, db_path: str | Path = DB_PATH) -> int:
    """`event` is a storage_ai.models.FileEvent -- kept as a positional
    duck-typed param (rather than importing models here) to avoid a
    database.py <-> models.py import cycle risk as the schema grows."""
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO file_events "
            "(timestamp, path, event_type, size, uid, username, attribution_source, pid, process_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.timestamp,
                event.path,
                event.event_type,
                event.size,
                event.uid,
                event.username,
                event.attribution_source,
                event.pid,
                event.process_name,
            ),
        )
        return cursor.lastrowid


def get_recent_file_events(since: float, limit: int = 500, db_path: str | Path = DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT timestamp, path, event_type, size, uid, username, attribution_source, pid, process_name "
            "FROM file_events WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    columns = ["timestamp", "path", "event_type", "size", "uid", "username", "attribution_source", "pid", "process_name"]
    return [dict(zip(columns, r)) for r in rows]


def upgrade_event_attribution(audit_event, tolerance_seconds: float = 5.0, db_path: str | Path = DB_PATH) -> bool:
    """Finds the most recent stat()-attributed file_events row for the same
    path within `tolerance_seconds` of an AuditFileEvent's timestamp, and
    upgrades it to real per-operation attribution from auditd. Both the
    watcher (inotify) and auditd fire for the same real-world operation
    within a fraction of a second of each other, so a several-second
    tolerance window is generous, not loose. Returns True if a match was
    found and updated."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM file_events WHERE path = ? AND ABS(timestamp - ?) <= ? "
            "AND attribution_source != 'audit' ORDER BY ABS(timestamp - ?) ASC LIMIT 1",
            (audit_event.path, audit_event.timestamp, tolerance_seconds, audit_event.timestamp),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE file_events SET username = ?, pid = ?, process_name = ?, attribution_source = 'audit' "
            "WHERE id = ?",
            (audit_event.username, audit_event.pid, audit_event.process_name, row[0]),
        )
        return True


def record_alert(alert, db_path: str | Path = DB_PATH) -> int:
    with connect(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO activity_alerts (timestamp, alert_type, username, detail, severity) "
            "VALUES (?, ?, ?, ?, ?)",
            (alert.timestamp, alert.alert_type, alert.username, alert.detail, alert.severity),
        )
        return cursor.lastrowid


def get_recent_alerts(since: float, limit: int = 200, db_path: str | Path = DB_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT timestamp, alert_type, username, detail, severity FROM activity_alerts "
            "WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    return [
        {"timestamp": r[0], "alert_type": r[1], "username": r[2], "detail": r[3], "severity": r[4]}
        for r in rows
    ]


def get_user_activity_summary(since: float, db_path: str | Path = DB_PATH) -> list[dict]:
    """Per-user event counts and bytes added, since `since` -- backs the
    Live Activity tab's per-user breakdown."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                COALESCE(username, '(unknown)') AS username,
                COUNT(*) AS event_count,
                SUM(CASE WHEN event_type IN ('created', 'modified') THEN COALESCE(size, 0) ELSE 0 END) AS bytes_added,
                SUM(CASE WHEN event_type = 'created' THEN 1 ELSE 0 END) AS created_count,
                SUM(CASE WHEN event_type = 'modified' THEN 1 ELSE 0 END) AS modified_count,
                SUM(CASE WHEN event_type = 'deleted' THEN 1 ELSE 0 END) AS deleted_count
            FROM file_events
            WHERE timestamp >= ?
            GROUP BY username
            ORDER BY event_count DESC
            """,
            (since,),
        ).fetchall()
    columns = ["username", "event_count", "bytes_added", "created_count", "modified_count", "deleted_count"]
    return [dict(zip(columns, r)) for r in rows]
