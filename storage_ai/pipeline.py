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
from storage_ai.duplicates import find_duplicates
from storage_ai.models import DuplicateGroup, FileRecord, Recommendation, StorageForecast, UnusedCandidate
from storage_ai.prediction import forecast_storage
from storage_ai.recommender import build_recommendations
from storage_ai.scanner import scan_directory
from storage_ai.unused import score_files


@dataclass
class AnalysisResult:
    root: str
    records: list[FileRecord]
    duplicate_groups: list[DuplicateGroup]
    unused_candidates: list[UnusedCandidate]
    forecast: StorageForecast
    recommendations: list[Recommendation]


def run_analysis(
    root: str | Path,
    on_progress: Callable[[str], None] | None = None,
) -> AnalysisResult:
    root = str(root)
    now = time.time()

    def _progress(message: str) -> None:
        if on_progress:
            on_progress(message)

    _progress("Scanning filesystem...")
    records = scan_directory(root)

    _progress(f"Scanned {len(records)} files. Detecting duplicates...")
    duplicate_groups = find_duplicates(records)

    _progress("Scoring unused files...")
    unused_candidates = score_files(records, now=now)

    _progress("Forecasting storage growth...")
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

    _progress("Building recommendations...")
    recommendations = build_recommendations(duplicate_groups, unused_candidates, forecast)

    _progress("Done.")
    return AnalysisResult(
        root=root,
        records=records,
        duplicate_groups=duplicate_groups,
        unused_candidates=unused_candidates,
        forecast=forecast,
        recommendations=recommendations,
    )
