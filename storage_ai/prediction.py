"""Storage growth forecasting.

Two data sources feed the same linear-regression forecast:

1. "snapshots" -- once this tool has scanned the same root at least twice,
   real (timestamp, total_size) points from database.py give a genuine
   time series of how the tree has grown between actual scans. This is the
   preferred source and gets more accurate the longer the tool is used.

2. "file-timestamps" -- on a first-ever scan there's no history yet, but the
   files themselves carry timestamps spanning months or years. Bucketing
   each file's modified-time into a month and treating cumulative size as a
   pseudo time series gives a reasonable growth-rate estimate immediately,
   without making the user wait for repeated scans to get any forecast at
   all. It's a weaker signal (it assumes files are rarely deleted) so it's
   only used as a fallback.

Both paths fit a simple linear regression (rate of bytes/day) and project
it forward against the current free space to estimate days-until-full.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from storage_ai.models import FileRecord, StorageForecast

_SECONDS_PER_DAY = 86400
_MIN_POINTS_FOR_REGRESSION = 2


def _linear_growth_rate(days: list[float], cumulative_bytes: list[float]) -> float:
    """Bytes/day slope via least-squares fit; 0.0 if the fit is degenerate."""
    if len(days) < _MIN_POINTS_FOR_REGRESSION or days[-1] == days[0]:
        return 0.0
    slope, _intercept = np.polyfit(days, cumulative_bytes, 1)
    return max(0.0, float(slope))


def _forecast_from_snapshots(snapshots: list[dict]) -> float | None:
    if len(snapshots) < _MIN_POINTS_FOR_REGRESSION:
        return None
    first_ts = snapshots[0]["taken_at"]
    days = [(s["taken_at"] - first_ts) / _SECONDS_PER_DAY for s in snapshots]
    sizes = [float(s["total_size"]) for s in snapshots]
    return _linear_growth_rate(days, sizes)


def _forecast_from_file_timestamps(records: list[FileRecord], now: float) -> float:
    """Bucket files by modified-month and fit growth on cumulative size,
    using the last 24 months of history so a handful of very old files
    don't flatten a recent growth trend."""
    monthly_totals: dict[int, int] = defaultdict(int)
    for record in records:
        months_ago = int((now - record.modified_time) / _SECONDS_PER_DAY / 30)
        if 0 <= months_ago <= 24:
            monthly_totals[months_ago] += record.size

    if len(monthly_totals) < _MIN_POINTS_FOR_REGRESSION:
        return 0.0

    months_ago_sorted = sorted(monthly_totals.keys(), reverse=True)
    days = [(-m * 30.0) for m in months_ago_sorted]
    cumulative = np.cumsum([monthly_totals[m] for m in months_ago_sorted]).tolist()
    return _linear_growth_rate(days, cumulative)


def forecast_storage(
    records: list[FileRecord],
    free_bytes: int,
    snapshots: list[dict],
    now: float,
) -> StorageForecast:
    total_size = sum(r.size for r in records)

    bytes_per_day = _forecast_from_snapshots(snapshots)
    source = "snapshots"
    if bytes_per_day is None:
        bytes_per_day = _forecast_from_file_timestamps(records, now)
        source = "file-timestamps"

    days_until_full = (free_bytes / bytes_per_day) if bytes_per_day > 0 else None
    projected_30_day = total_size + int(bytes_per_day * 30)

    return StorageForecast(
        current_total_bytes=total_size,
        free_bytes=free_bytes,
        bytes_per_day=bytes_per_day,
        days_until_full=days_until_full,
        projected_30_day_bytes=projected_30_day,
        history_source=source,
    )
