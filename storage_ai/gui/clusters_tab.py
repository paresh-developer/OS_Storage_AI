"""K-means file-cluster scatter (size vs. staleness) with a clickable
legend list."""

from __future__ import annotations

from PySide6.QtWidgets import QListWidgetItem

from storage_ai.gui.chart_tab import ChartTab, make_color_icon
from storage_ai.gui.palette import SCATTER_SAFE_PALETTE
from storage_ai.pipeline import AnalysisResult

_DIMMED_ALPHA = 0.12
_NORMAL_ALPHA = 0.7

_INFO_SUMMARY = "Files grouped by size and staleness using K-means clustering."
_INFO_DETAILS = (
    "This chart groups files by size and staleness using K-means clustering -- "
    "an unsupervised technique, independent of the 'likely unused' scoring on "
    "the Unused Files tab. Each point is one file: the x-axis is file size (log "
    "scale), the y-axis is days since it was last accessed.\n\n"
    "Cluster labels like 'Large & Stale' are relative to this scan's own median "
    "size and age, so they adapt to whatever folder you scan. Files in a "
    "'... & Stale' cluster, especially 'Large & Stale', are usually the best "
    "cleanup candidates.\n\n"
    "Click a legend row to highlight that cluster, or use Clear Selection to reset."
)


class ClustersTab(ChartTab):
    def __init__(self) -> None:
        super().__init__("About: File Clusters", _INFO_SUMMARY, _INFO_DETAILS)
        self._collections = []

    def update_results(self, result: AnalysisResult) -> None:
        self._reset_selection()

        self._ax.clear()
        self._collections = []
        self._ax.set_title("File clusters: size vs. staleness")

        clustering = result.clustering
        if clustering is None:
            self._ax.text(0.5, 0.5, "Not enough files yet\nfor meaningful clusters", ha="center", va="center")
            self._ax.set_xticks([])
            self._ax.set_yticks([])
        else:
            for i, summary in enumerate(clustering.summaries):
                points = [p for p in clustering.points if p.cluster_id == summary.cluster_id]
                color = SCATTER_SAFE_PALETTE[i % len(SCATTER_SAFE_PALETTE)]
                collection = self._ax.scatter(
                    [p.size for p in points],
                    [p.days_since_access for p in points],
                    color=color,
                    alpha=_NORMAL_ALPHA,
                )
                self._collections.append(collection)
                icon = make_color_icon(color)
                self._legend_list.addItem(QListWidgetItem(icon, f"{summary.label}  ({len(points)} files)"))
            self._ax.set_xscale("log")
            self._ax.set_xlabel("File size (log scale)")
            self._ax.set_ylabel("Days since last accessed")

        self._canvas.draw()

    def _apply_highlight(self, selected_row: int | None) -> None:
        for i, collection in enumerate(self._collections):
            if selected_row is None or i == selected_row:
                collection.set_alpha(_NORMAL_ALPHA)
            else:
                collection.set_alpha(_DIMMED_ALPHA)
