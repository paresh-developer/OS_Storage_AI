"""Ranked, plain-language recommendations combining duplicates, unused
files, and the storage forecast. Read-only -- actions are taken from the
Duplicates / Unused Files tabs, which is where the underlying file lists
live."""

from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from storage_ai.models import Recommendation
from storage_ai.utils import human_size

_COLUMNS = ["Type", "Recommendation", "Detail", "Est. savings", "Confidence"]
_KIND_LABELS = {
    "delete_duplicate": "Duplicate",
    "archive_unused": "Unused",
    "storage_warning": "Warning",
}


class RecommendationsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        self._summary = QLabel("Run a scan to see cleanup recommendations.")
        layout.addWidget(self._summary)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setColumnWidth(0, 90)
        self._table.setColumnWidth(1, 220)
        self._table.setColumnWidth(2, 400)
        self._table.setColumnWidth(3, 90)
        self._table.setColumnWidth(4, 90)
        layout.addWidget(self._table)

    def update_results(self, recommendations: list[Recommendation]) -> None:
        total_savings = sum(r.estimated_savings_bytes for r in recommendations)
        self._summary.setText(
            f"{len(recommendations)} recommendation(s) -- up to {human_size(total_savings)} recoverable. "
            "Apply changes from the Duplicates / Unused Files tabs."
        )

        self._table.setRowCount(len(recommendations))
        for row, rec in enumerate(recommendations):
            self._set_cell(row, 0, _KIND_LABELS.get(rec.kind, rec.kind))
            self._set_cell(row, 1, rec.title)
            self._set_cell(row, 2, rec.detail)
            self._set_cell(
                row, 3, human_size(rec.estimated_savings_bytes) if rec.estimated_savings_bytes else "--"
            )
            self._set_cell(row, 4, f"{rec.confidence:.0%}")

    def _set_cell(self, row: int, column: int, text: str) -> None:
        """Sets a cell's text and, so a truncated column still shows the full
        value, its tooltip too."""
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        self._table.setItem(row, column, item)
