"""Tests for the Live Activity tab's GUI logic: display population and the
start/stop control state machine. The underlying live-event capture is
already covered live in test_watcher.py; these tests focus on what the tab
itself does with data it's given."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from storage_ai import trend_detector
from storage_ai.gui.live_activity_tab import LiveActivityTab, _alert_examples_text


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def test_initial_state_shows_not_monitoring():
    tab = LiveActivityTab()

    assert tab._toggle_button.text() == "Start Live Monitoring"
    assert tab._path_field.isEnabled() is True
    assert tab._watcher is None


def test_start_monitoring_requires_a_folder(monkeypatch):
    tab = LiveActivityTab()
    warnings = []
    monkeypatch.setattr(
        "storage_ai.gui.live_activity_tab.QMessageBox.warning",
        lambda *a, **k: warnings.append(a) or None,
    )

    tab._path_field.setText("")
    tab._start_monitoring()

    assert warnings
    assert tab._watcher is None


def test_start_monitoring_shows_error_and_stays_unstarted_when_watch_fails(monkeypatch):
    """Regression test: a folder whose watch fails to start (e.g. inotify
    limit exceeded, bad path) must show a clear error and leave the tab in
    its normal not-monitoring state -- not silently record a half-started
    watcher that later crashes on stop() (see watcher.py's LiveWatcherError)."""
    tab = LiveActivityTab()
    errors = []
    monkeypatch.setattr(
        "storage_ai.gui.live_activity_tab.QMessageBox.critical",
        lambda *a, **k: errors.append(a) or None,
    )

    tab._path_field.setText("/definitely/does/not/exist/xyz")
    tab._start_monitoring()

    assert errors
    assert tab._watcher is None
    assert tab._toggle_button.text() == "Start Live Monitoring"
    assert tab._refresh_timer.isActive() is False

    tab.stop_if_monitoring()  # must not raise even though nothing started


def test_start_and_stop_monitoring_toggles_controls(tmp_path):
    tab = LiveActivityTab()
    tab._path_field.setText(str(tmp_path))

    tab._start_monitoring()
    assert tab._watcher is not None
    assert tab._toggle_button.text() == "Stop Live Monitoring"
    assert tab._path_field.isEnabled() is False
    assert tab._refresh_timer.isActive() is True

    tab._stop_monitoring()
    assert tab._watcher is None
    assert tab._toggle_button.text() == "Start Live Monitoring"
    assert tab._path_field.isEnabled() is True
    assert tab._refresh_timer.isActive() is False


def test_stop_if_monitoring_is_a_safe_noop_when_not_monitoring():
    tab = LiveActivityTab()
    tab.stop_if_monitoring()  # should not raise
    assert tab._watcher is None


def test_stop_if_monitoring_stops_an_active_watcher(tmp_path):
    tab = LiveActivityTab()
    tab._path_field.setText(str(tmp_path))
    tab._start_monitoring()

    tab.stop_if_monitoring()

    assert tab._watcher is None


def test_populate_events_table_renders_rows():
    tab = LiveActivityTab()
    events = [
        {"timestamp": 100.0, "path": "/a.txt", "event_type": "created", "size": 1000, "username": "alice"},
        {"timestamp": 200.0, "path": "/b.txt", "event_type": "deleted", "size": None, "username": None},
    ]

    tab._populate_events_table(events)

    assert tab._events_table.rowCount() == 2
    assert tab._events_table.item(1, 3).text() == "(unknown)"
    assert tab._events_table.item(1, 4).text() == "--"
    assert tab._events_table.item(0, 4).text() == "1000.0 B"


def test_populate_summary_table_renders_rows():
    tab = LiveActivityTab()
    summary = [
        {
            "username": "alice",
            "event_count": 5,
            "created_count": 2,
            "modified_count": 2,
            "deleted_count": 1,
            "bytes_added": 2048,
        }
    ]

    tab._populate_summary_table(summary)

    assert tab._summary_table.rowCount() == 1
    assert tab._summary_table.item(0, 0).text() == "alice"
    assert tab._summary_table.item(0, 5).text() == "2.0 KB"


def test_populate_alerts_list_shows_severity_marker_and_username():
    tab = LiveActivityTab()
    alerts = [
        {"severity": "warning", "username": "bob", "detail": "20 files deleted"},
        {"severity": "critical", "username": None, "detail": "100 changes"},
    ]

    tab._populate_alerts_list(alerts)

    assert tab._alerts_list.count() == 2
    assert "bob" in tab._alerts_list.item(0).text()
    assert "(unknown)" in tab._alerts_list.item(1).text()


def test_alerts_info_button_shows_all_four_alert_types(monkeypatch):
    tab = LiveActivityTab()
    shown = []
    monkeypatch.setattr(
        "storage_ai.gui.live_activity_tab.show_info_dialog",
        lambda parent, title, text: shown.append((title, text)) or None,
    )

    tab._show_alerts_info()

    assert shown
    title, text = shown[0]
    assert title == "About: Alerts"
    for phrase in ("Large file added", "Rapid deletes", "Rapid modifications", "Burst activity"):
        assert phrase in text


def test_alert_examples_text_reflects_actual_thresholds():
    text = _alert_examples_text()

    assert str(trend_detector.RAPID_DELETE_COUNT) in text
    assert str(trend_detector.RAPID_MODIFY_COUNT) in text
    assert str(trend_detector.BURST_EVENT_COUNT) in text
    assert f"{trend_detector.RAPID_DELETE_WINDOW_SECONDS}s" in text


def test_alert_examples_match_real_rendering_format():
    """The example strings shown in the info popup should be literal
    renderings of what _populate_alerts_list actually produces, not just
    similar-looking approximations."""
    tab = LiveActivityTab()
    tab._populate_alerts_list(
        [{"severity": "warning", "username": "bob", "detail": f"{trend_detector.RAPID_DELETE_COUNT} file(s) deleted in the last {trend_detector.RAPID_DELETE_WINDOW_SECONDS}s"}]
    )
    rendered = tab._alerts_list.item(0).text()

    assert rendered in _alert_examples_text()
