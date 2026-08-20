import pytest

from storage_ai.models import FileRecord
from storage_ai.prediction import forecast_storage

DAY = 86400


def test_uses_snapshot_history_when_available():
    now = 1000 * DAY
    records = [FileRecord("/a", 1000, ".dat", now, now, now, 0)]
    snapshots = [
        {"taken_at": now - 10 * DAY, "total_size": 1000, "file_count": 1, "free_bytes": 5000},
        {"taken_at": now, "total_size": 2000, "file_count": 2, "free_bytes": 4000},
    ]

    forecast = forecast_storage(records, free_bytes=4000, snapshots=snapshots, now=now)

    assert forecast.history_source == "snapshots"
    assert forecast.bytes_per_day == pytest.approx(100.0)
    assert forecast.days_until_full == pytest.approx(40.0)


def test_falls_back_to_file_timestamps_on_first_scan():
    now = 100 * DAY
    records = []
    for months_ago in range(10):
        records.append(
            FileRecord(
                path=f"/f{months_ago}",
                size=1000,
                extension=".dat",
                created_time=now - months_ago * 30 * DAY,
                modified_time=now - months_ago * 30 * DAY,
                accessed_time=now,
                depth=0,
            )
        )

    forecast = forecast_storage(records, free_bytes=100_000, snapshots=[], now=now)

    assert forecast.history_source == "file-timestamps"
    assert forecast.bytes_per_day > 0


def test_zero_growth_rate_gives_no_exhaustion_estimate():
    now = 10 * DAY
    records = [FileRecord("/a", 1000, ".dat", now, now, now, 0)]

    forecast = forecast_storage(records, free_bytes=5000, snapshots=[], now=now)

    assert forecast.days_until_full is None
