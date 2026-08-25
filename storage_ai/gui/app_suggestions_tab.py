"""App data suggestions tab: runs batch application storage-path
discovery (storage_ai.app_suggestions) across every process currently
running on this machine and lists what it found, each with the same kind
of advisory text the Recommendations tab shows for a scanned folder's
categories.

Independent of the folder-scan pipeline and of the Live Activity tab's
watcher -- this looks at the OS's running process table, not a folder you
pick or a live filesystem event stream, so it gets its own Run/Stop
controls rather than reusing either of those."""

from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from storage_ai import app_suggestions as app_suggestions_module
from storage_ai.app_suggestions import SEVERITY_CRITICAL, SEVERITY_LARGE, AppSuggestion
from storage_ai.gui.app_suggestions_worker import AppSuggestionsWorker, start_app_suggestions_scan
from storage_ai.gui.info_dialog import show_info_dialog
from storage_ai.models import ScanProgress
from storage_ai.utils import human_size

_COLUMNS = ["Application", "Discovered path", "Category / service", "Size on disk", "How it was found", "Confidence", "Suggestion"]

_SEVERITY_MARKER = {SEVERITY_LARGE: "⚠ ", SEVERITY_CRITICAL: "❗ "}
_SEVERITY_COLOR = {SEVERITY_LARGE: QColor("#a15c00"), SEVERITY_CRITICAL: QColor("#b00020")}

_INFO_SUMMARY = "Finds where currently-running applications store their data, and suggests what to do about it."


def _info_details() -> str:
    """A function, not a module-level constant, for the same reason
    live_activity_tab.py's _alert_examples_text() is one -- built from
    app_suggestions.py's actual threshold constants so this stays
    accurate if they're ever tuned, rather than baking today's numbers
    into a string at import time."""
    return (
        "Checks every distinct process currently running on this machine and tries to find "
        "where each one stores its data, without needing to already know that application:\n\n"
        "1. Live process introspection (/proc) -- what the running process's command line "
        "or open files actually show.\n"
        "2. Its config file, if one can be found and parsed (JSON/YAML/TOML/INI).\n"
        "3. An optional local, CPU-only language model, only as a last resort for a config "
        "file that exists but isn't in any of those formats.\n\n"
        "See docs/METHODOLOGY.md Section 8 for the full design, including the real bugs "
        "found and fixed while building tier 3.\n\n"
        "Only applications whose discovered path matches a category or known service with "
        "actual advice (e.g. \"consider log rotation\") are listed -- this is meant to be a "
        "short, actionable list, not a dump of every process on the machine.\n\n"
        "Nothing here is applied automatically: this only ever suggests. Confidence is highest "
        "for a live process observation, lower for a parsed config file, and lowest (and "
        "visibly discounted) for the optional local-model tier.\n\n"
        "The discovered path's real on-disk usage is measured (a filesystem walk, only for "
        "findings already worth showing) and flagged in the Size on disk column:\n"
        f"  ⚠  large -- {human_size(app_suggestions_module.LARGE_SIZE_BYTES)} or more\n"
        f"  ❗  critical -- {human_size(app_suggestions_module.CRITICAL_SIZE_BYTES)} or more\n"
        "Flagged rows sort to the top, ahead of unflagged ones, regardless of discovery "
        "confidence -- e.g. a confidently-found small cache directory still ranks below an "
        "unrotated multi-gigabyte log directory found with lower confidence."
    )


class AppSuggestionsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._worker: AppSuggestionsWorker | None = None
        self._suggestions: list[AppSuggestion] = []

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_control_bar())

        self._status_label = QLabel("Click Run to check every running application for storage suggestions.")
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setColumnWidth(0, 110)
        self._table.setColumnWidth(1, 240)
        self._table.setColumnWidth(2, 130)
        self._table.setColumnWidth(3, 110)
        self._table.setColumnWidth(4, 140)
        self._table.setColumnWidth(5, 80)
        self._table.setColumnWidth(6, 300)
        layout.addWidget(self._table)

    def _build_control_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self._run_button = QPushButton("Run")
        self._run_button.clicked.connect(self._start_run)
        row.addWidget(self._run_button)

        self._stop_button = QPushButton("Stop")
        self._stop_button.clicked.connect(self._stop_run)
        self._stop_button.setVisible(False)
        row.addWidget(self._stop_button)

        row.addStretch()

        info_button = QPushButton("ℹ")
        info_button.setFixedSize(24, 24)
        info_button.setToolTip(_INFO_SUMMARY)
        info_button.clicked.connect(self._show_info)
        row.addWidget(info_button)

        return row

    def _show_info(self) -> None:
        show_info_dialog(self, "About: App Data Suggestions", _info_details())

    def _start_run(self) -> None:
        self._run_button.setText("Rerun")
        self._run_button.setEnabled(False)
        self._stop_button.setVisible(True)
        self._stop_button.setEnabled(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText("Starting...")

        self._thread, self._worker = start_app_suggestions_scan(
            on_progress=self._on_progress,
            on_finished=self._on_finished,
            on_failed=self._on_failed,
            on_cancelled=self._on_cancelled,
        )

    def _stop_run(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._stop_button.setEnabled(False)
        self._status_label.setText("Stopping... (finishing the current application check first)")

    def stop_if_running(self) -> None:
        """Public hook for the main window to call on shutdown, so a
        forgotten-about run doesn't outlive the app (same reasoning as
        LiveActivityTab.stop_if_monitoring). Blocks briefly for the worker
        thread to actually exit -- cancelling and returning immediately
        would let Qt tear down the QThread object while the OS thread is
        still finishing its current iteration, which is a real crash
        ("QThread: Destroyed while thread is still running"), not just a
        warning."""
        if self._worker is None:
            return
        self._worker.cancel()
        if self._thread is not None:
            self._thread.wait(5000)

    def _reset_controls(self) -> None:
        self._run_button.setEnabled(True)
        self._stop_button.setVisible(False)
        self._progress_bar.setVisible(False)

    def _on_progress(self, progress: ScanProgress) -> None:
        self._progress_bar.setValue(round(progress.fraction * 100))
        self._status_label.setText(progress.message)

    def _on_finished(self, suggestions: list[AppSuggestion]) -> None:
        self._reset_controls()
        self._suggestions = suggestions
        flagged = sum(1 for s in suggestions if s.severity != app_suggestions_module.SEVERITY_NORMAL)
        if not suggestions:
            message = "Done -- no actionable suggestions found among the applications currently running."
        elif flagged:
            message = f"Done -- {len(suggestions)} suggestion(s) found, {flagged} flagged for unusually large disk usage."
        else:
            message = f"Done -- {len(suggestions)} suggestion(s) found."
        self._status_label.setText(message)
        self._populate_table()

    def _on_failed(self, message: str) -> None:
        self._reset_controls()
        self._status_label.setText("Failed.")
        QMessageBox.critical(self, "App discovery failed", message)

    def _on_cancelled(self) -> None:
        self._reset_controls()
        self._status_label.setText("Stopped.")

    def _populate_table(self) -> None:
        self._table.setRowCount(len(self._suggestions))
        for row, suggestion in enumerate(self._suggestions):
            color = _SEVERITY_COLOR.get(suggestion.severity)
            marker = _SEVERITY_MARKER.get(suggestion.severity, "")
            self._set_cell(row, 0, suggestion.app_name)
            self._set_cell(row, 1, suggestion.path)
            self._set_cell(row, 2, suggestion.known_service or suggestion.category.replace("_", " "))
            self._set_cell(row, 3, f"{marker}{human_size(suggestion.size_bytes)}", color=color)
            self._set_cell(row, 4, f"{suggestion.source} ({suggestion.detail})")
            self._set_cell(row, 5, f"{suggestion.confidence:.2f}")
            self._set_cell(row, 6, suggestion.advice)

    def _set_cell(self, row: int, column: int, text: str, color: QColor | None = None) -> None:
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        if color is not None:
            item.setForeground(color)
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        self._table.setItem(row, column, item)
