"""A info dialog that always fits the screen: a scroll area with a fixed
maximum size, instead of QMessageBox.information, which has no scrolling
and just keeps growing to fit its content. That's fine for a short static
explanation, but once an info button's text includes a per-scan detail
block (e.g. a long directory breakdown from legend_detail.py, or several
app-discovery findings), the dialog can grow taller than the screen with
no way to see the rest."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
)

_MAX_WIDTH = 640
_MAX_HEIGHT = 520
_MIN_HEIGHT = 160


def show_info_dialog(parent, title: str, text: str) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)

    layout = QVBoxLayout(dialog)

    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)

    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setContentsMargins(10, 10, 10, 10)
    scroll.setWidget(label)
    layout.addWidget(scroll)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)

    dialog.resize(_MAX_WIDTH, _MAX_HEIGHT)
    dialog.setMinimumHeight(_MIN_HEIGHT)
    dialog.exec()
