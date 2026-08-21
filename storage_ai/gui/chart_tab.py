"""Shared base for a chart-plus-legend tab: a matplotlib chart on one side,
a clickable legend list plus a Clear Selection button and an info button on
the other. Clicking a legend row brings that chart element to full opacity
with a highlight outline and dims everything else; clicking the same row
again, or clicking Clear Selection, restores the default view. This is the
one interaction pattern all four chart tabs share, so it lives here once
rather than being reimplemented per chart.

Subclasses are responsible for building their own matplotlib artists in
`update_results` (storing references to whatever they'll need to
dim/highlight later) and populating `self._legend_list` with one row per
artist, in the same order. `_apply_highlight(selected_row)` is the only
method a subclass must implement -- `selected_row` is the row to bring to
full opacity, or None to show everything at normal opacity.

Each subclass also supplies `info_title` / `info_summary` / `info_details`
to `super().__init__(...)`: `info_summary` is a one-line tooltip shown on
hover (over the chart and the info button); `info_details` is the fuller
explanation shown when the info button is clicked.
"""

from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_LEGEND_TOOLTIP = "Click a row to highlight it in the chart and dim the rest. Click it again, or use Clear Selection, to restore the default view."
_SWATCH_SIZE = 14


def make_color_icon(color, size: int = _SWATCH_SIZE) -> QIcon:
    """Builds a small solid-color swatch icon for a legend row, from
    whatever color matplotlib actually rendered that artist in -- accepts
    a hex/named string (e.g. `line.get_color()`) or an RGB(A) float
    sequence in [0, 1] (e.g. `wedge.get_facecolor()`), so the swatch is
    always exactly right whether the color was auto-assigned or explicit."""
    if isinstance(color, str):
        qcolor = QColor(color)
    else:
        values = [float(v) for v in color]
        r, g, b = values[0], values[1], values[2]
        a = values[3] if len(values) > 3 else 1.0
        qcolor = QColor.fromRgbF(r, g, b, a)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(qcolor)
    painter.setPen(QColor(0, 0, 0, 70))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    painter.end()
    return QIcon(pixmap)


class ChartTab(QWidget):
    def __init__(
        self,
        info_title: str,
        info_summary: str,
        info_details: str,
        figsize: tuple[float, float] = (6.5, 5.5),
    ) -> None:
        super().__init__()
        self._info_title = info_title
        self._info_details = info_details
        self._selected_row: int | None = None

        layout = QHBoxLayout(self)

        self._figure = Figure(figsize=figsize)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._canvas.setToolTip(info_summary)
        self._ax = self._figure.add_subplot(111)
        layout.addWidget(self._canvas, 3)

        side_panel = QVBoxLayout()

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Legend"))
        header_row.addStretch()
        self._info_button = QPushButton("ℹ")  # "i" in a circle
        self._info_button.setFixedSize(24, 24)
        self._info_button.setToolTip(info_summary)
        self._info_button.clicked.connect(self._show_info)
        header_row.addWidget(self._info_button)
        side_panel.addLayout(header_row)

        self._legend_list = QListWidget()
        self._legend_list.setIconSize(QSize(_SWATCH_SIZE, _SWATCH_SIZE))
        self._legend_list.setToolTip(_LEGEND_TOOLTIP)
        self._legend_list.itemClicked.connect(self._on_item_clicked)
        side_panel.addWidget(self._legend_list)

        self._clear_button = QPushButton("Clear Selection")
        self._clear_button.setToolTip("Restores the chart's default colors.")
        self._clear_button.setEnabled(False)
        self._clear_button.clicked.connect(self._clear_selection_clicked)
        side_panel.addWidget(self._clear_button)

        side_container = QWidget()
        side_container.setLayout(side_panel)
        side_container.setMaximumWidth(300)
        layout.addWidget(side_container, 1)

    def _show_info(self) -> None:
        QMessageBox.information(self, self._info_title, self._info_details)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        row = self._legend_list.row(item)
        if row == self._selected_row:
            self._selected_row = None
            self._legend_list.setCurrentRow(-1)
        else:
            self._selected_row = row
        self._clear_button.setEnabled(self._selected_row is not None)
        self._apply_highlight(self._selected_row)
        self._canvas.draw_idle()

    def _clear_selection_clicked(self) -> None:
        if self._selected_row is None:
            return
        self._selected_row = None
        self._legend_list.setCurrentRow(-1)
        self._clear_button.setEnabled(False)
        self._apply_highlight(None)
        self._canvas.draw_idle()

    def _reset_selection(self) -> None:
        """Called at the start of a fresh `update_results` so a redraw
        never leaves a stale selection/highlight from the previous scan."""
        self._selected_row = None
        self._clear_button.setEnabled(False)
        self._legend_list.blockSignals(True)
        self._legend_list.setCurrentRow(-1)
        self._legend_list.blockSignals(False)
        self._legend_list.clear()

    def _apply_highlight(self, selected_row: int | None) -> None:
        """Bring `selected_row`'s artist to full opacity and dim the rest;
        `None` means show everything at normal opacity."""
        raise NotImplementedError
