"""Likely-unused files tab: sortable table with archive/trash actions for
whichever rows the user checks."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from storage_ai.actions import archive_file, trash_file
from storage_ai.models import UnusedCandidate
from storage_ai.utils import human_size

_COLUMNS = ["", "Path", "Size", "Last accessed (days)", "Score", "Reason"]


class UnusedTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._candidates: list[UnusedCandidate] = []
        self._root = ""

        layout = QVBoxLayout(self)
        self._summary = QLabel("Run a scan to find unused files.")
        layout.addWidget(self._summary)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setColumnWidth(0, 30)
        self._table.setColumnWidth(1, 400)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 150)
        self._table.setColumnWidth(4, 70)
        self._table.setColumnWidth(5, 220)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        self._archive_button = QPushButton("Archive checked files")
        self._archive_button.clicked.connect(self._archive_checked)
        self._trash_button = QPushButton("Send checked files to trash")
        self._trash_button.clicked.connect(self._trash_checked)
        buttons.addWidget(self._archive_button)
        buttons.addWidget(self._trash_button)
        buttons.addStretch()
        layout.addLayout(buttons)

    def update_results(self, candidates: list[UnusedCandidate], root: str, score_threshold: float = 0.6) -> None:
        self._candidates = [c for c in candidates if c.score >= score_threshold]
        self._root = root

        total_size = sum(c.size for c in self._candidates)
        self._summary.setText(
            f"{len(self._candidates)} likely-unused file(s) -- {human_size(total_size)} could be freed."
        )

        self._table.setRowCount(len(self._candidates))
        for row, candidate in enumerate(self._candidates):
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(checkbox_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checkbox_item.setCheckState(Qt.CheckState.Unchecked)
            self._table.setItem(row, 0, checkbox_item)
            self._set_cell(row, 1, candidate.path)
            self._set_cell(row, 2, human_size(candidate.size))
            self._set_cell(row, 3, f"{candidate.days_since_access:.0f}")
            self._set_cell(row, 4, f"{candidate.score:.2f}")
            self._set_cell(row, 5, candidate.reason)

    def _set_cell(self, row: int, column: int, text: str) -> None:
        """Sets a cell's text and, so a truncated column still shows the full
        value, its tooltip too."""
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        self._table.setItem(row, column, item)

    def _checked_paths(self) -> list[str]:
        paths = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                paths.append(self._table.item(row, 1).text())
        return paths

    def _archive_checked(self) -> None:
        paths = self._checked_paths()
        if not paths:
            QMessageBox.information(self, "Nothing selected", "Check at least one file first.")
            return

        failures = []
        for path in paths:
            try:
                archive_file(path, self._root)
            except OSError as exc:
                failures.append(f"{path}: {exc}")

        if failures:
            QMessageBox.warning(self, "Some files could not be archived", "\n".join(failures))
        self.update_results([c for c in self._candidates if c.path not in paths], self._root)

    def _trash_checked(self) -> None:
        paths = self._checked_paths()
        if not paths:
            QMessageBox.information(self, "Nothing selected", "Check at least one file first.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm",
            f"Send {len(paths)} file(s) to the trash? This can be undone from your OS trash bin.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        failures = []
        for path in paths:
            try:
                trash_file(path)
            except OSError as exc:
                failures.append(f"{path}: {exc}")

        if failures:
            QMessageBox.warning(self, "Some files could not be trashed", "\n".join(failures))
        self.update_results([c for c in self._candidates if c.path not in paths], self._root)
