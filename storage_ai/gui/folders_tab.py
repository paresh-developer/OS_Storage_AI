"""Storage-by-top-level-folder treemap with a clickable legend list."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from matplotlib.patches import Rectangle
from PySide6.QtWidgets import QListWidgetItem

from storage_ai.gui.chart_tab import ChartTab, make_color_icon
from storage_ai.gui.palette import CATEGORICAL_PALETTE, MUTED_OTHER
from storage_ai.pipeline import AnalysisResult
from storage_ai.treemap import compute_treemap
from storage_ai.utils import human_size

_MAX_TREEMAP_ITEMS = 8  # matches the 8 real categorical slots; overflow folds to "(other)"
_DIMMED_ALPHA = 0.35
_NORMAL_EDGE_WIDTH = 1.5
_HIGHLIGHT_EDGE_WIDTH = 3.0

_INFO_SUMMARY = "Which top-level folders are using the most space (rectangle area = size)."
_INFO_DETAILS = (
    "This treemap shows which top-level folders under the scanned root are using "
    "the most space -- each rectangle's area is proportional to that folder's "
    "total size. The 8 largest folders are shown individually; anything smaller "
    "is grouped into '(other)'.\n\n"
    "Click a legend row to highlight that folder's rectangle, or use Clear "
    "Selection to reset."
)


def _folder_totals(records, root: str) -> dict[str, int]:
    root_path = Path(root)
    totals: dict[str, int] = defaultdict(int)
    for record in records:
        try:
            relative = Path(record.path).relative_to(root_path)
        except ValueError:
            relative = Path(record.path)
        top_level = relative.parts[0] if len(relative.parts) > 1 else "(root)"
        totals[top_level] += record.size
    return totals


class FoldersTab(ChartTab):
    def __init__(self) -> None:
        super().__init__("About: Storage by Top-Level Folder", _INFO_SUMMARY, _INFO_DETAILS)
        self._patches = []

    def update_results(self, result: AnalysisResult) -> None:
        self._reset_selection()

        self._ax.clear()
        self._patches = []
        self._ax.set_title("Storage by top-level folder")

        totals = _folder_totals(result.records, result.root)
        items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        top_items, other_items = items[:_MAX_TREEMAP_ITEMS], items[_MAX_TREEMAP_ITEMS:]
        if other_items:
            top_items.append(("(other)", sum(size for _, size in other_items)))

        rects = compute_treemap(top_items, width=1.0, height=1.0)
        colors = [
            MUTED_OTHER if rect.label == "(other)" else CATEGORICAL_PALETTE[i % len(CATEGORICAL_PALETTE)]
            for i, rect in enumerate(rects)
        ]
        for rect, color in zip(rects, colors):
            patch = Rectangle(
                (rect.x, rect.y),
                rect.width,
                rect.height,
                facecolor=color,
                edgecolor="white",
                linewidth=_NORMAL_EDGE_WIDTH,
            )
            self._ax.add_patch(patch)
            self._patches.append(patch)
            if rect.width > 0.08 and rect.height > 0.06:
                self._ax.text(
                    rect.x + rect.width / 2,
                    rect.y + rect.height / 2,
                    f"{rect.label}\n{human_size(rect.value)}",
                    ha="center",
                    va="center",
                    fontsize=7,
                )
            icon = make_color_icon(patch.get_facecolor())
            self._legend_list.addItem(QListWidgetItem(icon, f"{rect.label}  --  {human_size(rect.value)}"))

        self._ax.set_xlim(0, 1)
        self._ax.set_ylim(0, 1)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._canvas.draw()

    def _apply_highlight(self, selected_row: int | None) -> None:
        for i, patch in enumerate(self._patches):
            if selected_row is None:
                patch.set_alpha(1.0)
                patch.set_edgecolor("white")
                patch.set_linewidth(_NORMAL_EDGE_WIDTH)
            elif i == selected_row:
                patch.set_alpha(1.0)
                patch.set_edgecolor("black")
                patch.set_linewidth(_HIGHLIGHT_EDGE_WIDTH)
            else:
                patch.set_alpha(_DIMMED_ALPHA)
                patch.set_edgecolor("white")
                patch.set_linewidth(_NORMAL_EDGE_WIDTH)
