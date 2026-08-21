"""Overview tab: headline numbers and the storage-by-category breakdown.
The four charts (file types, forecast, folders, clusters) each live in
their own tab -- see file_types_tab.py / forecast_tab.py / folders_tab.py /
clusters_tab.py."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from storage_ai.path_classifier import (
    CATEGORY_APPLICATION_DATA,
    CATEGORY_CACHE,
    CATEGORY_LOG,
    CATEGORY_OTHER,
    CATEGORY_SYSTEM,
    CATEGORY_TRASH,
    CATEGORY_USER_DATA,
)
from storage_ai.pipeline import AnalysisResult
from storage_ai.utils import human_duration_days, human_size as _human_size

_CATEGORY_DISPLAY_ORDER = [
    (CATEGORY_APPLICATION_DATA, "Application data"),
    (CATEGORY_LOG, "Logs"),
    (CATEGORY_CACHE, "Cache"),
    (CATEGORY_TRASH, "Trash"),
    (CATEGORY_SYSTEM, "System"),
    (CATEGORY_USER_DATA, "User data"),
    (CATEGORY_OTHER, "Other"),
]


class DashboardTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self._summary_labels: dict[str, QLabel] = {}
        top_row.addWidget(self._build_summary_box())
        top_row.addWidget(self._build_category_box())
        layout.addLayout(top_row)
        layout.addStretch()

    def _build_summary_box(self) -> QGroupBox:
        box = QGroupBox("Overview")
        grid = QGridLayout(box)
        fields = [
            "root",
            "file_count",
            "total_size",
            "free_space",
            "growth_rate",
            "days_until_full",
        ]
        titles = {
            "root": "Scanned folder",
            "file_count": "Files scanned",
            "total_size": "Total size",
            "free_space": "Free space",
            "growth_rate": "Growth rate",
            "days_until_full": "Est. time to full",
        }
        for row, field in enumerate(fields):
            grid.addWidget(QLabel(f"{titles[field]}:"), row, 0)
            value_label = QLabel("--")
            self._summary_labels[field] = value_label
            grid.addWidget(value_label, row, 1)
        return box

    def _build_category_box(self) -> QGroupBox:
        box = QGroupBox("Storage by category")
        box_layout = QVBoxLayout(box)
        self._category_label = QLabel("--")
        self._category_label.setWordWrap(True)
        box_layout.addWidget(self._category_label)
        return box

    def update_results(self, result: AnalysisResult) -> None:
        self._summary_labels["root"].setText(result.root)
        self._summary_labels["file_count"].setText(f"{len(result.records):,}")
        self._summary_labels["total_size"].setText(_human_size(result.forecast.current_total_bytes))
        self._summary_labels["free_space"].setText(_human_size(result.forecast.free_bytes))
        self._summary_labels["growth_rate"].setText(
            f"{_human_size(result.forecast.bytes_per_day)}/day ({result.forecast.history_source})"
        )
        days_full = result.forecast.days_until_full
        self._summary_labels["days_until_full"].setText(
            f"~{human_duration_days(days_full)}" if days_full is not None else "no growth trend detected"
        )

        self._category_label.setText(_format_category_summary(result.category_totals))


def _format_category_summary(category_totals: dict[tuple[str, str | None], int]) -> str:
    lines = []
    for category, display_name in _CATEGORY_DISPLAY_ORDER:
        matching = {service: total for (cat, service), total in category_totals.items() if cat == category}
        if not matching:
            continue
        if category == CATEGORY_APPLICATION_DATA:
            for service, total in sorted(matching.items(), key=lambda kv: kv[1], reverse=True):
                lines.append(f"{service or display_name} (protected): {_human_size(total)}")
        else:
            total = sum(matching.values())
            suffix = " (protected)" if category == CATEGORY_SYSTEM else ""
            lines.append(f"{display_name}{suffix}: {_human_size(total)}")
    return "\n".join(lines) if lines else "No categorized storage yet."
