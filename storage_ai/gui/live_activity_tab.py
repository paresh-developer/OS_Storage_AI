"""Live create/modify/delete monitoring for a folder, with per-user
activity trends -- the GUI-embedded convenience path over watcher.py.

This toggle is for single-machine, while-the-app-is-open monitoring. It
does not poll auditd (that stays server-only, in watcher_service.py, to
keep this simple and avoid duplicating that machinery in the GUI thread),
so user attribution here is file-ownership based (see _INFO_DETAILS) --
plain, not per-operation. For "runs even when the GUI is closed" server
monitoring with real per-operation attribution, run watcher_service.py
directly (optionally as a systemd service).
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from storage_ai import database, trend_detector
from storage_ai.models import file_event_from_row
from storage_ai.utils import human_size
from storage_ai.watcher import LiveWatcher, LiveWatcherError

_REFRESH_INTERVAL_MS = 2000
_DISPLAY_WINDOW_SECONDS = 3600  # show the last hour of activity
_ALERT_COOLDOWN_SECONDS = 300

_INFO_SUMMARY = "Live create/modify/delete monitoring for a folder, with per-user activity trends."
_INFO_DETAILS = (
    "Starts a live filesystem watcher on the selected folder (using the OS's native "
    "file-change notifications) and records every create, modify, and delete as it "
    "happens, with rate-based trend alerts (large file added, rapid deletes, etc.).\n\n"
    "User attribution here is based on file ownership -- who OWNS the file, which is "
    "not always who just performed this specific operation. A delete shows no user at "
    "all, since there's nothing left to check ownership on once the file is gone.\n\n"
    "For real per-operation attribution (who actually ran the command, from which "
    "process), run this app's standalone watcher service with --enable-audit on Linux "
    "(requires root and the 'audit' package) -- see docs/METHODOLOGY.md.\n\n"
    "This toggle stops when the app closes. For monitoring that keeps running "
    "independently of the GUI (e.g. on a headless server), run:\n"
    "  python -m storage_ai.watcher_service <folder>\n"
    "optionally installed as a systemd service."
)

_EVENT_COLUMNS = ["Time", "Event", "Path", "User", "Size"]
_SUMMARY_COLUMNS = ["User", "Events", "Created", "Modified", "Deleted", "Bytes Added"]

_SEVERITY_MARKER = {"info": "ℹ", "warning": "⚠", "critical": "❗"}


def _alert_examples_text() -> str:
    """Built from trend_detector's actual thresholds rather than hardcoded
    numbers, so this stays accurate if those constants are ever tuned --
    and formatted exactly like `_populate_alerts_list` renders a real row,
    so these examples are literally what you'd see, not an approximation."""
    large_file_example = (
        f"{_SEVERITY_MARKER['info']} alice: /srv/shared/backup.tar.gz "
        f"({human_size(trend_detector.LARGE_FILE_BYTES)})"
    )
    rapid_delete_example = (
        f"{_SEVERITY_MARKER['warning']} bob: {trend_detector.RAPID_DELETE_COUNT} file(s) deleted "
        f"in the last {trend_detector.RAPID_DELETE_WINDOW_SECONDS}s"
    )
    rapid_modify_example = (
        f"{_SEVERITY_MARKER['warning']} carol: {trend_detector.RAPID_MODIFY_COUNT} file(s) modified "
        f"in the last {trend_detector.RAPID_MODIFY_WINDOW_SECONDS}s"
    )
    burst_example = (
        f"{_SEVERITY_MARKER['critical']} dave: {trend_detector.BURST_EVENT_COUNT} file(s) changed "
        f"in the last {trend_detector.BURST_WINDOW_SECONDS}s"
    )

    return (
        "Alerts fire on plain, explainable thresholds -- not a learned model -- so "
        "each one can be justified in exactly the terms it fired in. Each example "
        "below is formatted exactly as it appears in the list above:\n\n"
        f"Large file added (info)\n"
        f"  {large_file_example}\n"
        f"  Fires once per file that reaches {human_size(trend_detector.LARGE_FILE_BYTES)} or more.\n\n"
        f"Rapid deletes (warning)\n"
        f"  {rapid_delete_example}\n"
        f"  Fires when one user deletes {trend_detector.RAPID_DELETE_COUNT}+ files within "
        f"{trend_detector.RAPID_DELETE_WINDOW_SECONDS} seconds.\n\n"
        f"Rapid modifications (warning)\n"
        f"  {rapid_modify_example}\n"
        f"  Fires when one user modifies {trend_detector.RAPID_MODIFY_COUNT}+ files within "
        f"{trend_detector.RAPID_MODIFY_WINDOW_SECONDS} seconds.\n\n"
        f"Burst activity (critical)\n"
        f"  {burst_example}\n"
        "  Fires when one user's total file operations (any mix of create/modify/"
        f"delete) reach {trend_detector.BURST_EVENT_COUNT}+ within {trend_detector.BURST_WINDOW_SECONDS} seconds.\n\n"
        f"Each alert re-fires at most once every {_ALERT_COOLDOWN_SECONDS // 60} minutes per "
        "user, so a sustained burst won't spam this list.\n\n"
        "Usernames shown here reflect file ownership, not necessarily who actually "
        "performed the action -- see the top info button for what that means and "
        "how to get real per-operation attribution.\n\n"
        "Thresholds are tunable in storage_ai/trend_detector.py."
    )


class LiveActivityTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._watcher: LiveWatcher | None = None
        self._monitoring_root: str | None = None
        self._recent_alert_keys: dict[tuple, float] = {}

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_control_bar())

        self._status_label = QLabel("Not monitoring. Choose a folder and click Start.")
        layout.addWidget(self._status_label)

        content_row = QHBoxLayout()
        content_row.addWidget(self._build_events_box(), 3)
        content_row.addWidget(self._build_side_column(), 2)
        layout.addLayout(content_row)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh_display)

    def _build_control_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Watch folder:"))

        self._path_field = QLineEdit()
        self._path_field.setPlaceholderText("Select a folder to monitor live...")
        row.addWidget(self._path_field)

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._browse_for_folder)
        row.addWidget(browse_button)
        self._browse_button = browse_button

        self._toggle_button = QPushButton("Start Live Monitoring")
        self._toggle_button.clicked.connect(self._toggle_monitoring)
        row.addWidget(self._toggle_button)

        info_button = QPushButton("ℹ")
        info_button.setFixedSize(24, 24)
        info_button.setToolTip(_INFO_SUMMARY)
        info_button.clicked.connect(self._show_info)
        row.addWidget(info_button)

        return row

    def _build_events_box(self) -> QGroupBox:
        box = QGroupBox("Recent activity (last hour)")
        box_layout = QVBoxLayout(box)
        self._events_table = QTableWidget()
        self._events_table.setColumnCount(len(_EVENT_COLUMNS))
        self._events_table.setHorizontalHeaderLabels(_EVENT_COLUMNS)
        self._events_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._events_table.setColumnWidth(0, 140)
        self._events_table.setColumnWidth(1, 70)
        self._events_table.setColumnWidth(2, 400)
        self._events_table.setColumnWidth(3, 90)
        self._events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        box_layout.addWidget(self._events_table)
        return box

    def _build_side_column(self) -> QWidget:
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)

        summary_box = QGroupBox("Per-user summary (last hour)")
        summary_layout = QVBoxLayout(summary_box)
        self._summary_table = QTableWidget()
        self._summary_table.setColumnCount(len(_SUMMARY_COLUMNS))
        self._summary_table.setHorizontalHeaderLabels(_SUMMARY_COLUMNS)
        self._summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for column_index, width in enumerate([70, 55, 60, 65, 60, 90]):
            self._summary_table.setColumnWidth(column_index, width)
        summary_layout.addWidget(self._summary_table)
        column.addWidget(summary_box, 1)

        alerts_box = QGroupBox("Alerts")
        alerts_layout = QVBoxLayout(alerts_box)

        alerts_header = QHBoxLayout()
        alerts_header.addStretch()
        alerts_info_button = QPushButton("ℹ")
        alerts_info_button.setFixedSize(20, 20)
        alerts_info_button.setToolTip("What alerts can fire, with examples -- click for details.")
        alerts_info_button.clicked.connect(self._show_alerts_info)
        alerts_header.addWidget(alerts_info_button)
        alerts_layout.addLayout(alerts_header)

        self._alerts_list = QListWidget()
        self._alerts_list.setToolTip("Rate-based trend alerts -- click the ℹ above for the exact thresholds and examples.")
        alerts_layout.addWidget(self._alerts_list)
        column.addWidget(alerts_box, 1)

        return container

    def _show_info(self) -> None:
        QMessageBox.information(self, "About: Live Activity Monitoring", _INFO_DETAILS)

    def _show_alerts_info(self) -> None:
        QMessageBox.information(self, "About: Alerts", _alert_examples_text())

    def _browse_for_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder to monitor")
        if folder:
            self._path_field.setText(folder)

    def _toggle_monitoring(self) -> None:
        if self._watcher is None:
            self._start_monitoring()
        else:
            self._stop_monitoring()

    def stop_if_monitoring(self) -> None:
        """Public hook for the main window to call on shutdown, so a
        forgotten-about watcher doesn't outlive the app."""
        if self._watcher is not None:
            self._stop_monitoring()

    def _start_monitoring(self) -> None:
        root = self._path_field.text().strip()
        if not root:
            QMessageBox.warning(self, "No folder selected", "Choose a folder to monitor first.")
            return

        watcher = LiveWatcher([root], self._on_file_event)
        try:
            watcher.start()
        except LiveWatcherError as exc:
            QMessageBox.critical(self, "Could not start monitoring", str(exc))
            return

        self._watcher = watcher
        self._monitoring_root = root
        self._recent_alert_keys.clear()

        self._path_field.setEnabled(False)
        self._browse_button.setEnabled(False)
        self._toggle_button.setText("Stop Live Monitoring")
        self._status_label.setText(f"Monitoring {root}...")
        self._refresh_timer.start()

    def _stop_monitoring(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
        self._watcher = None
        self._refresh_timer.stop()

        self._path_field.setEnabled(True)
        self._browse_button.setEnabled(True)
        self._toggle_button.setText("Start Live Monitoring")
        self._status_label.setText("Not monitoring. Choose a folder and click Start.")

    def _on_file_event(self, event) -> None:
        """Runs on the watchdog observer thread -- must never touch a Qt
        widget directly, only the database (a fresh sqlite3 connection per
        call, so this is safe to call from any thread)."""
        database.record_file_event(event)

    def _refresh_display(self) -> None:
        now = time.time()
        since = now - _DISPLAY_WINDOW_SECONDS

        events = database.get_recent_file_events(since=since, limit=300)
        self._populate_events_table(events)

        summary = database.get_user_activity_summary(since=since)
        self._populate_summary_table(summary)

        self._check_trends(now, since)
        alerts = database.get_recent_alerts(since=since, limit=50)
        self._populate_alerts_list(alerts)

        self._status_label.setText(f"Monitoring {self._monitoring_root} -- {len(events)} event(s) in the last hour.")

    def _check_trends(self, now: float, since: float) -> None:
        rows = database.get_recent_file_events(since=since, limit=5000)
        file_events = [file_event_from_row(r) for r in rows]
        for alert in trend_detector.detect_alerts(file_events, now=now):
            key = (alert.alert_type, alert.username)
            last_fired = self._recent_alert_keys.get(key)
            if last_fired is not None and now - last_fired < _ALERT_COOLDOWN_SECONDS:
                continue
            database.record_alert(alert)
            self._recent_alert_keys[key] = now

    def _populate_events_table(self, events: list[dict]) -> None:
        self._events_table.setRowCount(len(events))
        for row, event in enumerate(events):
            when = time.strftime("%H:%M:%S", time.localtime(event["timestamp"]))
            self._set_cell(self._events_table, row, 0, when)
            self._set_cell(self._events_table, row, 1, event["event_type"])
            self._set_cell(self._events_table, row, 2, event["path"])
            self._set_cell(self._events_table, row, 3, event["username"] or "(unknown)")
            self._set_cell(self._events_table, row, 4, human_size(event["size"]) if event["size"] is not None else "--")

    def _populate_summary_table(self, summary: list[dict]) -> None:
        self._summary_table.setRowCount(len(summary))
        for row, entry in enumerate(summary):
            self._set_cell(self._summary_table, row, 0, entry["username"])
            self._set_cell(self._summary_table, row, 1, str(entry["event_count"]))
            self._set_cell(self._summary_table, row, 2, str(entry["created_count"]))
            self._set_cell(self._summary_table, row, 3, str(entry["modified_count"]))
            self._set_cell(self._summary_table, row, 4, str(entry["deleted_count"]))
            self._set_cell(self._summary_table, row, 5, human_size(entry["bytes_added"]))

    def _populate_alerts_list(self, alerts: list[dict]) -> None:
        self._alerts_list.clear()
        for alert in alerts:
            marker = _SEVERITY_MARKER.get(alert["severity"], "")
            username = alert["username"] or "(unknown)"
            self._alerts_list.addItem(f"{marker} {username}: {alert['detail']}")

    @staticmethod
    def _set_cell(table: QTableWidget, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        table.setItem(row, column, item)
