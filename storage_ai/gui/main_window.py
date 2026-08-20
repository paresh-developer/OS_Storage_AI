from __future__ import annotations

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from storage_ai.gui.dashboard_tab import DashboardTab
from storage_ai.gui.duplicates_tab import DuplicatesTab
from storage_ai.gui.recommendations_tab import RecommendationsTab
from storage_ai.gui.scan_worker import ScanWorker, start_scan
from storage_ai.gui.unused_tab import UnusedTab
from storage_ai.models import ScanProgress
from storage_ai.pipeline import AnalysisResult
from storage_ai.utils import human_duration_seconds


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Storage AI -- intelligent storage cleanup assistant")
        self.resize(1100, 800)

        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        layout.addLayout(self._build_scan_bar())

        self._status_label = QLabel("Choose a folder and click Scan to begin.")
        layout.addWidget(self._status_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._tabs = QTabWidget()
        self._dashboard_tab = DashboardTab()
        self._duplicates_tab = DuplicatesTab()
        self._unused_tab = UnusedTab()
        self._recommendations_tab = RecommendationsTab()
        self._tabs.addTab(self._dashboard_tab, "Dashboard")
        self._tabs.addTab(self._duplicates_tab, "Duplicates")
        self._tabs.addTab(self._unused_tab, "Unused Files")
        self._tabs.addTab(self._recommendations_tab, "Recommendations")
        layout.addWidget(self._tabs)

    def _build_scan_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Folder:"))

        self._path_field = QLineEdit()
        self._path_field.setPlaceholderText("Select a folder to analyze...")
        row.addWidget(self._path_field)

        self._browse_button = QPushButton("Browse...")
        self._browse_button.clicked.connect(self._browse_for_folder)
        row.addWidget(self._browse_button)

        self._scan_button = QPushButton("Scan")
        self._scan_button.clicked.connect(self._start_scan)
        row.addWidget(self._scan_button)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self._cancel_scan)
        self._cancel_button.setVisible(False)
        row.addWidget(self._cancel_button)

        return row

    def _browse_for_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder to analyze")
        if folder:
            self._path_field.setText(folder)

    def _start_scan(self) -> None:
        root = self._path_field.text().strip()
        if not root:
            QMessageBox.warning(self, "No folder selected", "Choose a folder to analyze first.")
            return

        self._scan_button.setEnabled(False)
        self._browse_button.setEnabled(False)
        self._cancel_button.setVisible(True)
        self._cancel_button.setEnabled(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText("Starting scan...")

        self._thread, self._worker = start_scan(
            root,
            on_progress=self._on_progress,
            on_finished=self._on_finished,
            on_failed=self._on_failed,
            on_cancelled=self._on_cancelled,
        )

    def _cancel_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._cancel_button.setEnabled(False)
        self._status_label.setText("Cancelling... (finishing the current file/group first)")

    def _reset_scan_controls(self) -> None:
        self._scan_button.setEnabled(True)
        self._browse_button.setEnabled(True)
        self._cancel_button.setVisible(False)
        self._progress_bar.setVisible(False)

    def _on_progress(self, progress: ScanProgress) -> None:
        self._progress_bar.setValue(round(progress.fraction * 100))
        message = progress.message
        if progress.eta_seconds is not None:
            message += f" (~{human_duration_seconds(progress.eta_seconds)} remaining)"
        self._status_label.setText(message)

    def _on_finished(self, result: AnalysisResult) -> None:
        self._reset_scan_controls()
        self._status_label.setText(
            f"Scan complete: {len(result.records)} files analyzed in {result.root}."
        )

        self._dashboard_tab.update_results(result)
        self._duplicates_tab.update_results(result.duplicate_groups)
        self._unused_tab.update_results(result.unused_candidates, result.root)
        self._recommendations_tab.update_results(result.recommendations)

    def _on_failed(self, message: str) -> None:
        self._reset_scan_controls()
        self._status_label.setText("Scan failed.")
        QMessageBox.critical(self, "Scan failed", message)

    def _on_cancelled(self) -> None:
        self._reset_scan_controls()
        self._status_label.setText("Scan cancelled.")
