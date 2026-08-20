"""Overview tab: headline numbers plus a file-type breakdown and a storage
growth forecast chart."""

from __future__ import annotations

from collections import defaultdict

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from storage_ai.pipeline import AnalysisResult
from storage_ai.utils import human_duration_days, human_size as _human_size


class DashboardTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        self._summary_labels: dict[str, QLabel] = {}
        layout.addWidget(self._build_summary_box())

        charts_row = QHBoxLayout()
        self._extension_figure = Figure(figsize=(4, 3))
        self._extension_canvas = FigureCanvasQTAgg(self._extension_figure)
        charts_row.addWidget(self._extension_canvas)

        self._forecast_figure = Figure(figsize=(4, 3))
        self._forecast_canvas = FigureCanvasQTAgg(self._forecast_figure)
        charts_row.addWidget(self._forecast_canvas)

        layout.addLayout(charts_row)

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

        self._render_extension_chart(result)
        self._render_forecast_chart(result)

    def _render_extension_chart(self, result: AnalysisResult) -> None:
        totals: dict[str, int] = defaultdict(int)
        for record in result.records:
            totals[record.extension or "(none)"] += record.size

        top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
        self._extension_figure.clear()
        ax = self._extension_figure.add_subplot(111)
        if top:
            ax.pie([size for _, size in top], labels=[ext for ext, _ in top], autopct="%1.0f%%")
        ax.set_title("Storage by file type")
        self._extension_canvas.draw()

    def _render_forecast_chart(self, result: AnalysisResult) -> None:
        forecast = result.forecast
        self._forecast_figure.clear()
        ax = self._forecast_figure.add_subplot(111)
        days = [0, 30]
        sizes = [forecast.current_total_bytes, forecast.projected_30_day_bytes]
        ax.plot(days, sizes, marker="o", label="Projected usage")
        ax.axhline(
            forecast.current_total_bytes + forecast.free_bytes,
            color="red",
            linestyle="--",
            label="Disk capacity",
        )
        ax.set_xlabel("Days from now")
        ax.set_ylabel("Bytes")
        ax.set_title("30-day storage forecast")
        ax.legend(fontsize="small")
        self._forecast_canvas.draw()
