"""Tests DashboardTab's "storage by category" box, in particular the info
button's per-category directory breakdown -- the actual directories
behind each category's total, not just the total itself."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from storage_ai.gui.dashboard_tab import DashboardTab
from storage_ai.models import FileRecord, StorageForecast
from storage_ai.path_classifier import PathClassification
from storage_ai.pipeline import AnalysisResult


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _forecast():
    return StorageForecast(
        current_total_bytes=10_000,
        free_bytes=90_000,
        bytes_per_day=100.0,
        days_until_full=900.0,
        projected_30_day_bytes=13_000,
        history_source="file-timestamps",
    )


def _result(records, classifications, category_totals):
    return AnalysisResult(
        root="/demo",
        records=records,
        duplicate_groups=[],
        unused_candidates=[],
        forecast=_forecast(),
        recommendations=[],
        clustering=None,
        category_totals=category_totals,
        classifications=classifications,
    )


def test_category_detail_lists_directories_behind_each_category():
    records = [
        FileRecord("/var/log/app/a.log", 100, ".log", 0, 0, 0, 0),
        FileRecord("/home/user/Videos/movie.mp4", 5000, ".mp4", 0, 0, 0, 0),
    ]
    classifications = {
        "/var/log/app/a.log": PathClassification(category="log", known_service=None),
        "/home/user/Videos/movie.mp4": PathClassification(category="user_data", known_service=None),
    }
    category_totals = {("log", None): 100, ("user_data", None): 5000}

    tab = DashboardTab()
    tab.update_results(_result(records, classifications, category_totals))

    detail = tab._category_detail_text
    assert "/var/log/app" in detail
    assert "/home/user/Videos" in detail


def test_category_detail_groups_application_data_by_service():
    records = [
        FileRecord("/var/lib/postgresql/14/main/base.dat", 9000, "", 0, 0, 0, 0),
    ]
    classifications = {
        "/var/lib/postgresql/14/main/base.dat": PathClassification(category="application_data", known_service="PostgreSQL"),
    }
    category_totals = {("application_data", "PostgreSQL"): 9000}

    tab = DashboardTab()
    tab.update_results(_result(records, classifications, category_totals))

    detail = tab._category_detail_text
    assert "PostgreSQL" in detail
    assert "/var/lib/postgresql/14/main" in detail


def test_category_detail_before_any_scan_is_a_placeholder():
    tab = DashboardTab()
    assert "Run a scan" in tab._category_detail_text


def test_category_detail_handles_no_categorized_storage():
    tab = DashboardTab()
    tab.update_results(_result([], {}, {}))

    assert "No categorized storage yet." in tab._category_detail_text
