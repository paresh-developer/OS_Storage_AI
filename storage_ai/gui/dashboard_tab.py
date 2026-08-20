"""Overview tab: headline numbers plus four charts -- a file-type
breakdown, a storage growth forecast, a folder-size treemap, and a
K-means cluster view of files by size and staleness."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
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
from storage_ai.treemap import compute_treemap
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

_MAX_TREEMAP_ITEMS = 8  # matches the 8 real categorical slots below; overflow folds to "(other)"

# Fixed categorical order from the validated reference palette (dataviz skill,
# references/palette.md) -- adjacent-pair CVD-safe for up to all 8 slots, which
# covers the treemap's "top folder" categories. A scatter plot must compare
# every pair of series, not just adjacent ones, and only the first 3 slots
# clear that stricter all-pairs bar -- so the cluster chart is capped there
# (see clustering.py's matching max_clusters=3 default).
_CATEGORICAL_PALETTE = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]
_MUTED_OTHER = "#898781"
_SCATTER_SAFE_PALETTE = _CATEGORICAL_PALETTE[:3]


class DashboardTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self._summary_labels: dict[str, QLabel] = {}
        top_row.addWidget(self._build_summary_box())
        top_row.addWidget(self._build_category_box())
        layout.addLayout(top_row)

        charts_grid = QGridLayout()

        self._extension_figure = Figure(figsize=(4.2, 3.2))
        self._extension_canvas = FigureCanvasQTAgg(self._extension_figure)
        charts_grid.addWidget(self._extension_canvas, 0, 0)

        self._forecast_figure = Figure(figsize=(4.2, 3.2))
        self._forecast_canvas = FigureCanvasQTAgg(self._forecast_figure)
        charts_grid.addWidget(self._forecast_canvas, 0, 1)

        self._treemap_figure = Figure(figsize=(4.2, 3.2))
        self._treemap_canvas = FigureCanvasQTAgg(self._treemap_figure)
        charts_grid.addWidget(self._treemap_canvas, 1, 0)

        self._cluster_figure = Figure(figsize=(4.2, 3.2))
        self._cluster_canvas = FigureCanvasQTAgg(self._cluster_figure)
        charts_grid.addWidget(self._cluster_canvas, 1, 1)

        layout.addLayout(charts_grid)

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

        self._render_extension_chart(result)
        self._render_forecast_chart(result)
        self._render_treemap_chart(result)
        self._render_cluster_chart(result)

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

    def _render_treemap_chart(self, result: AnalysisResult) -> None:
        self._treemap_figure.clear()
        ax = self._treemap_figure.add_subplot(111)
        ax.set_title("Storage by top-level folder")

        totals = _folder_totals(result.records, result.root)
        items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        top_items, other_items = items[:_MAX_TREEMAP_ITEMS], items[_MAX_TREEMAP_ITEMS:]
        if other_items:
            top_items.append(("(other)", sum(size for _, size in other_items)))

        rects = compute_treemap(top_items, width=1.0, height=1.0)
        colors = [
            _MUTED_OTHER if rect.label == "(other)" else _CATEGORICAL_PALETTE[i % len(_CATEGORICAL_PALETTE)]
            for i, rect in enumerate(rects)
        ]
        for rect, color in zip(rects, colors):
            ax.add_patch(
                Rectangle((rect.x, rect.y), rect.width, rect.height, facecolor=color, edgecolor="white", linewidth=1.5)
            )
            if rect.width > 0.08 and rect.height > 0.06:
                label = f"{rect.label}\n{_human_size(rect.value)}"
                ax.text(
                    rect.x + rect.width / 2,
                    rect.y + rect.height / 2,
                    label,
                    ha="center",
                    va="center",
                    fontsize=7,
                )
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xticks([])
        ax.set_yticks([])
        self._treemap_canvas.draw()

    def _render_cluster_chart(self, result: AnalysisResult) -> None:
        self._cluster_figure.clear()
        ax = self._cluster_figure.add_subplot(111)
        ax.set_title("File clusters: size vs. staleness")

        clustering = result.clustering
        if clustering is None:
            ax.text(0.5, 0.5, "Not enough files yet\nfor meaningful clusters", ha="center", va="center")
            ax.set_xticks([])
            ax.set_yticks([])
        else:
            label_by_cluster = {s.cluster_id: s.label for s in clustering.summaries}
            color_by_cluster = {
                s.cluster_id: _SCATTER_SAFE_PALETTE[i % len(_SCATTER_SAFE_PALETTE)]
                for i, s in enumerate(clustering.summaries)
            }

            for cluster_id in label_by_cluster:
                points = [p for p in clustering.points if p.cluster_id == cluster_id]
                ax.scatter(
                    [p.size for p in points],
                    [p.days_since_access for p in points],
                    label=f"{label_by_cluster[cluster_id]} ({len(points)})",
                    color=color_by_cluster[cluster_id],
                    alpha=0.7,
                )
            ax.set_xscale("log")
            ax.set_xlabel("File size (log scale)")
            ax.set_ylabel("Days since last accessed")
            ax.legend(fontsize="small", loc="upper left")

        self._cluster_canvas.draw()


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
