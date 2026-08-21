"""Storage-by-file-type pie chart with a clickable legend list."""

from __future__ import annotations

from collections import defaultdict

from PySide6.QtWidgets import QListWidgetItem

from storage_ai.gui.chart_tab import ChartTab, make_color_icon
from storage_ai.pipeline import AnalysisResult
from storage_ai.utils import human_size

_DIMMED_ALPHA = 0.25
_NORMAL_EDGE_WIDTH = 1.0
_HIGHLIGHT_EDGE_WIDTH = 2.5

_INFO_SUMMARY = "Storage used by each file extension (top 8 by size)."
_INFO_DETAILS = (
    "This pie chart shows how your scanned storage is split across file extensions "
    "-- the 8 largest categories by total size.\n\n"
    "Each legend row lists one file type and its total size. Click a row to "
    "highlight that slice and dim the rest; click it again, or use Clear "
    "Selection, to return to the default view."
)


class FileTypesTab(ChartTab):
    def __init__(self) -> None:
        super().__init__("About: Storage by File Type", _INFO_SUMMARY, _INFO_DETAILS)
        self._wedges = []

    def update_results(self, result: AnalysisResult) -> None:
        self._reset_selection()

        totals: dict[str, int] = defaultdict(int)
        for record in result.records:
            totals[record.extension or "(none)"] += record.size
        top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]

        self._ax.clear()
        self._wedges = []
        if top:
            self._wedges, _texts, _autotexts = self._ax.pie(
                [size for _, size in top], labels=[ext for ext, _ in top], autopct="%1.0f%%"
            )
            for wedge, (ext, size) in zip(self._wedges, top):
                icon = make_color_icon(wedge.get_facecolor())
                self._legend_list.addItem(QListWidgetItem(icon, f"{ext}  --  {human_size(size)}"))
        self._ax.set_title("Storage by file type")
        self._canvas.draw()

    def _apply_highlight(self, selected_row: int | None) -> None:
        for i, wedge in enumerate(self._wedges):
            if selected_row is None:
                wedge.set_alpha(1.0)
                wedge.set_edgecolor("white")
                wedge.set_linewidth(_NORMAL_EDGE_WIDTH)
            elif i == selected_row:
                wedge.set_alpha(1.0)
                wedge.set_edgecolor("black")
                wedge.set_linewidth(_HIGHLIGHT_EDGE_WIDTH)
            else:
                wedge.set_alpha(_DIMMED_ALPHA)
                wedge.set_edgecolor("white")
                wedge.set_linewidth(_NORMAL_EDGE_WIDTH)
