"""End-to-end analysis pipeline: scan -> duplicates -> unused -> forecast ->
recommendations, with the snapshot persisted for future forecasts.

This is the single entry point the GUI (and any CLI/tests) should call --
it's what keeps `gui/` a thin presentation layer over logic that's fully
testable without Qt.
"""

from __future__ import annotations

import shutil
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from storage_ai import database
from storage_ai.category_advisor import build_category_recommendations
from storage_ai.clustering import ClusteringResult, cluster_files
from storage_ai.duplicates import find_duplicates
from storage_ai.models import (
    DuplicateGroup,
    FileRecord,
    Recommendation,
    ScanProgress,
    StorageForecast,
    UnusedCandidate,
)
from storage_ai.path_classifier import classify_path
from storage_ai.prediction import forecast_storage
from storage_ai.recommender import build_recommendations
from storage_ai.scanner import count_files, scan_directory
from storage_ai.unused import score_files

# Fixed milestones for the stages after scanning -- these are fast and
# bounded (no per-item total to compute a real fraction from), so progress
# through them just advances to the next milestone on completion rather
# than reporting fine-grained percentages. Scanning itself gets a real,
# file-count-based fraction within its own [_SCAN_START, _SCAN_END] band.
_COUNT_DONE = 0.03
_SCAN_START = _COUNT_DONE
_SCAN_END = 0.85
_CLASSIFY_DONE = 0.88
_DUPLICATES_DONE = 0.92
_UNUSED_DONE = 0.95
_FORECAST_DONE = 0.97
_RECOMMENDATIONS_DONE = 0.99


@dataclass
class AnalysisResult:
    root: str
    records: list[FileRecord]
    duplicate_groups: list[DuplicateGroup]
    unused_candidates: list[UnusedCandidate]
    forecast: StorageForecast
    recommendations: list[Recommendation]
    clustering: ClusteringResult | None
    category_totals: dict[tuple[str, str | None], int]


def run_analysis(
    root: str | Path,
    on_progress: Callable[[ScanProgress], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> AnalysisResult:
    root = str(root)
    now = time.time()

    def _progress(message: str, fraction: float, eta_seconds: float | None = None) -> None:
        if on_progress:
            on_progress(ScanProgress(message=message, fraction=fraction, eta_seconds=eta_seconds))

    _progress("Counting files...", 0.0)
    total_files = count_files(root, cancel_check=cancel_check)

    _progress(f"Scanning {total_files} files...", _SCAN_START)
    scan_start_time = time.time()

    def _on_scan_progress(scanned: int) -> None:
        scan_fraction = min(1.0, scanned / total_files) if total_files > 0 else 1.0
        elapsed = time.time() - scan_start_time
        rate = scanned / elapsed if elapsed > 0 else 0.0
        remaining = max(0, total_files - scanned)
        eta = (remaining / rate) if rate > 0 else None
        _progress(
            f"Scanning... {scanned}/{total_files} files",
            _SCAN_START + scan_fraction * (_SCAN_END - _SCAN_START),
            eta_seconds=eta,
        )

    records = scan_directory(root, on_progress=_on_scan_progress, cancel_check=cancel_check)

    _progress("Classifying system, log, cache, and application-data paths...", _SCAN_END)
    classifications = {r.path: classify_path(r.path) for r in records}
    category_totals: dict[tuple[str, str | None], int] = defaultdict(int)
    for record in records:
        c = classifications[record.path]
        category_totals[(c.category, c.known_service)] += record.size

    # Files under a live service's data directory (or real OS system paths)
    # are excluded from every "is this stale/duplicate/clusterable" analysis
    # below -- access-time heuristics are not safe to apply to a running
    # database's own files. They still count toward totals/forecast/category
    # breakdown above, just never toward a delete/archive recommendation.
    analyzable_records = [r for r in records if not classifications[r.path].protected]

    _progress(f"Scanned {len(records)} files. Detecting duplicates...", _CLASSIFY_DONE)
    duplicate_groups = find_duplicates(analyzable_records, cancel_check=cancel_check)

    _progress("Scoring unused files...", _DUPLICATES_DONE)
    unused_candidates = score_files(analyzable_records, now=now)

    _progress("Forecasting storage growth...", _UNUSED_DONE)
    total_size = sum(r.size for r in records)
    free_bytes = shutil.disk_usage(root).free
    snapshots = database.get_snapshots(root)
    forecast = forecast_storage(records, free_bytes, snapshots, now)

    extension_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        bucket = extension_totals[record.extension or "(none)"]
        bucket[0] += record.size
        bucket[1] += 1

    database.record_snapshot(
        root_path=root,
        total_size=total_size,
        file_count=len(records),
        free_bytes=free_bytes,
        extension_totals={ext: tuple(v) for ext, v in extension_totals.items()},
        taken_at=now,
    )

    _progress("Building recommendations...", _FORECAST_DONE)
    category_recommendations = build_category_recommendations(dict(category_totals))
    recommendations = build_recommendations(duplicate_groups, unused_candidates, forecast, category_recommendations)

    _progress("Clustering files by size and staleness...", _RECOMMENDATIONS_DONE)
    clustering = cluster_files(analyzable_records, now=now)

    _progress("Done.", 1.0, eta_seconds=0)
    return AnalysisResult(
        root=root,
        records=records,
        duplicate_groups=duplicate_groups,
        unused_candidates=unused_candidates,
        forecast=forecast,
        recommendations=recommendations,
        clustering=clustering,
        category_totals=dict(category_totals),
    )
