"""Shared data structures used across the scanning, analysis, and GUI layers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileRecord:
    """Metadata captured for a single file during a scan."""

    path: str
    size: int
    extension: str
    created_time: float
    modified_time: float
    accessed_time: float
    depth: int


@dataclass
class DuplicateGroup:
    """A set of files with identical content."""

    file_hash: str
    size: int
    files: list[str]
    keep: str
    wasted_space: int = field(init=False)

    def __post_init__(self) -> None:
        self.wasted_space = self.size * (len(self.files) - 1)


@dataclass
class UnusedCandidate:
    """A file flagged as likely unused, with a 0-1 confidence score."""

    path: str
    size: int
    days_since_access: float
    days_since_modified: float
    score: float
    reason: str


@dataclass
class StorageForecast:
    """Projected storage growth for a scanned root."""

    current_total_bytes: int
    free_bytes: int
    bytes_per_day: float
    days_until_full: float | None
    projected_30_day_bytes: int
    history_source: str  # "snapshots" or "file-timestamps"


@dataclass
class Recommendation:
    """A single actionable cleanup/archiving suggestion."""

    kind: str  # "delete_duplicate" | "archive_unused" | "storage_warning"
    title: str
    detail: str
    estimated_savings_bytes: int
    confidence: float
    targets: list[str]


@dataclass
class ScanProgress:
    """A single progress update from run_analysis.

    `fraction` is an overall 0-1 completion estimate across the *whole*
    pipeline, not just the current stage -- the scanning stage (by far the
    most variable in duration) gets a real fraction computed from an
    upfront file count; the fast, bounded stages after it (duplicates,
    unused-scoring, forecasting, clustering, recommendations) just advance
    through fixed milestones. `eta_seconds` is only ever populated during
    the scanning stage, where there's an actual rate to extrapolate from.
    """

    message: str
    fraction: float
    eta_seconds: float | None = None


@dataclass
class FileEvent:
    """A single create/modify/delete event, as observed live by the
    watcher service (watcher.py) and optionally upgraded with real
    per-operation user attribution once/if auditd correlation succeeds
    (audit_log.py)."""

    timestamp: float
    path: str
    event_type: str  # "created" | "modified" | "deleted"
    size: int | None  # None for a deleted file, or if the stat() race lost
    uid: int | None  # owning uid from stat(), when available
    username: str | None
    attribution_source: str  # "stat" | "audit" | "unknown"
    pid: int | None = None
    process_name: str | None = None


@dataclass
class ActivityAlert:
    """A detected trend/anomaly in recent file activity -- a plain
    threshold rule, not a black-box model (see trend_detector.py)."""

    timestamp: float
    alert_type: str  # "large_file_added" | "rapid_deletes" | "rapid_modifications" | "burst_activity"
    username: str | None
    detail: str
    severity: str  # "info" | "warning" | "critical"


def file_event_from_row(row: dict) -> FileEvent:
    """Rebuilds a FileEvent from a database.get_recent_file_events() row --
    shared by watcher_service.py and the GUI's Live Activity tab so both
    read the same dict shape the same way."""
    return FileEvent(
        timestamp=row["timestamp"],
        path=row["path"],
        event_type=row["event_type"],
        size=row["size"],
        uid=row["uid"],
        username=row["username"],
        attribution_source=row["attribution_source"],
        pid=row["pid"],
        process_name=row["process_name"],
    )
