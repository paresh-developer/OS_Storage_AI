"""30-day storage forecast line chart with a clickable legend list."""

from __future__ import annotations

from PySide6.QtWidgets import QListWidgetItem

from storage_ai.gui.chart_tab import ChartTab, make_color_icon
from storage_ai.pipeline import AnalysisResult

_DIMMED_ALPHA = 0.25
_NORMAL_WIDTH = 2.0
_HIGHLIGHT_WIDTH = 4.0

_INFO_SUMMARY = "Projected storage growth over the next 30 days vs. your total disk size."
_INFO_DETAILS = (
    "This chart projects how much this folder's storage will grow over the next "
    "30 days, based on its current growth rate (see the Dashboard tab for whether "
    "that estimate comes from repeated scans or from file timestamps on a first "
    "scan).\n\n"
    "'Projected usage' is the forecasted growth line. 'Disk capacity' is your "
    "drive's total size, shown for reference so you can see how close usage is "
    "to the limit.\n\n"
    "Click a legend row to highlight that line, or use Clear Selection to reset."
)


class ForecastTab(ChartTab):
    def __init__(self) -> None:
        super().__init__("About: 30-Day Storage Forecast", _INFO_SUMMARY, _INFO_DETAILS)
        self._lines = []

    def update_results(self, result: AnalysisResult) -> None:
        self._reset_selection()

        forecast = result.forecast
        self._ax.clear()
        days = [0, 30]
        sizes = [forecast.current_total_bytes, forecast.projected_30_day_bytes]

        (usage_line,) = self._ax.plot(days, sizes, marker="o", label="Projected usage", linewidth=_NORMAL_WIDTH)
        capacity_line = self._ax.axhline(
            forecast.current_total_bytes + forecast.free_bytes,
            color="red",
            linestyle="--",
            label="Disk capacity",
            linewidth=_NORMAL_WIDTH,
        )
        self._lines = [usage_line, capacity_line]

        self._ax.set_xlabel("Days from now")
        self._ax.set_ylabel("Bytes")
        self._ax.set_title("30-day storage forecast")

        self._legend_list.addItem(QListWidgetItem(make_color_icon(usage_line.get_color()), "Projected usage"))
        self._legend_list.addItem(QListWidgetItem(make_color_icon(capacity_line.get_color()), "Disk capacity"))
        self._canvas.draw()

    def _apply_highlight(self, selected_row: int | None) -> None:
        for i, line in enumerate(self._lines):
            if selected_row is None or i == selected_row:
                line.set_alpha(1.0)
                line.set_linewidth(_HIGHLIGHT_WIDTH if i == selected_row else _NORMAL_WIDTH)
            else:
                line.set_alpha(_DIMMED_ALPHA)
                line.set_linewidth(_NORMAL_WIDTH)
