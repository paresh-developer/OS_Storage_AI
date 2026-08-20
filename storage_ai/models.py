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
