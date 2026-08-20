"""Integration test for the safety guarantee that protected paths
(system/application-data) never surface as delete/archive candidates, even
though they still count toward totals and the category breakdown."""

from __future__ import annotations

import os
import time

import pytest

from storage_ai import pipeline
from storage_ai.exceptions import ScanCancelled
from storage_ai.path_classifier import PathClassification


def test_protected_files_excluded_from_duplicates_and_unused(tmp_path, monkeypatch):
    protected_dir = tmp_path / "protected_db"
    protected_dir.mkdir()
    protected_file_a = protected_dir / "data_a.bin"
    protected_file_b = protected_dir / "data_b.bin"
    content = b"x" * 10_000
    protected_file_a.write_bytes(content)
    protected_file_b.write_bytes(content)  # exact duplicate, but of a protected file

    normal_file = tmp_path / "notes.txt"
    normal_file.write_text("hello")

    old_time = time.time() - 400 * 86400
    os.utime(protected_file_a, (old_time, old_time))
    os.utime(protected_file_b, (old_time, old_time))

    def fake_classify_path(path, **kwargs):
        if str(protected_dir) in path:
            return PathClassification(category="application_data", known_service="TestDB")
        return PathClassification(category="user_data")

    monkeypatch.setattr(pipeline, "classify_path", fake_classify_path)
    monkeypatch.setattr(pipeline.database, "record_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(pipeline.database, "get_snapshots", lambda root: [])

    result = pipeline.run_analysis(tmp_path)

    # Still counted in totals and the category breakdown...
    assert len(result.records) == 3
    assert result.category_totals[("application_data", "TestDB")] == 20_000

    # ...but never surfaced as a duplicate or unused-file candidate, despite
    # being an exact duplicate pair that's 400 days old.
    assert result.duplicate_groups == []
    assert all(c.path != str(protected_file_a) for c in result.unused_candidates)
    assert all(c.path != str(protected_file_b) for c in result.unused_candidates)
    assert all(
        str(protected_file_a) not in r.targets and str(protected_file_b) not in r.targets
        for r in result.recommendations
    )


def _quiet_db(monkeypatch):
    monkeypatch.setattr(pipeline.database, "record_snapshot", lambda **kwargs: None)
    monkeypatch.setattr(pipeline.database, "get_snapshots", lambda root: [])


def test_progress_reaches_100_percent_and_reports_message_and_eta(tmp_path, monkeypatch):
    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("x" * 100)
    _quiet_db(monkeypatch)

    updates = []
    pipeline.run_analysis(tmp_path, on_progress=updates.append)

    assert updates[0].fraction == 0.0
    assert updates[-1].fraction == 1.0
    assert all(0.0 <= u.fraction <= 1.0 for u in updates)
    # fraction is monotonically non-decreasing across the whole run
    assert all(a.fraction <= b.fraction for a, b in zip(updates, updates[1:]))
    # an ETA shows up at least once during the scanning stage
    assert any(u.eta_seconds is not None for u in updates)


def test_cancel_check_stops_the_scan_stage(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("hello")
    _quiet_db(monkeypatch)

    with pytest.raises(ScanCancelled):
        pipeline.run_analysis(tmp_path, cancel_check=lambda: True)


def test_cancel_check_stops_partway_through_a_larger_scan(tmp_path, monkeypatch):
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("x")
    _quiet_db(monkeypatch)

    calls = {"count": 0}

    def cancel_after_a_few_checks():
        calls["count"] += 1
        return calls["count"] > 3

    with pytest.raises(ScanCancelled):
        pipeline.run_analysis(tmp_path, cancel_check=cancel_after_a_few_checks)

    # cancelled partway through, not on the very first check
    assert calls["count"] > 3
