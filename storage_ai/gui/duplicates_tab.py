"""Duplicate files tab: one row per file, grouped visually by duplicate set,
with checkboxes to select which copies to send to the trash."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from storage_ai.actions import trash_file
from storage_ai.models import DuplicateGroup
from storage_ai.utils import human_size


def _set_all_tooltips(item: QTreeWidgetItem) -> None:
    """Show each cell's full text on hover, for when a column (most often
    the File column with a long path) is narrower than its content."""
    for column in range(item.columnCount()):
        text = item.text(column)
        if text:
            item.setToolTip(column, text)


class DuplicatesTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._groups: list[DuplicateGroup] = []

        layout = QVBoxLayout(self)
        self._summary = QLabel("Run a scan to find duplicate files.")
        layout.addWidget(self._summary)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["File", "Size", "Role"])
        header = self._tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._tree.setColumnWidth(0, 450)
        self._tree.setColumnWidth(1, 90)
        self._tree.setColumnWidth(2, 90)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self._tree)

        buttons = QHBoxLayout()
        self._trash_button = QPushButton("Send checked copies to trash")
        self._trash_button.clicked.connect(self._trash_checked)
        buttons.addWidget(self._trash_button)
        buttons.addStretch()
        layout.addLayout(buttons)

    def update_results(self, groups: list[DuplicateGroup]) -> None:
        self._groups = groups
        self._tree.clear()

        total_wasted = sum(g.wasted_space for g in groups)
        self._summary.setText(
            f"{len(groups)} duplicate group(s) found -- {human_size(total_wasted)} recoverable."
        )

        for group in groups:
            parent = QTreeWidgetItem([f"{len(group.files)} copies", human_size(group.size), ""])
            _set_all_tooltips(parent)
            self._tree.addTopLevelItem(parent)
            for file_path in group.files:
                is_keeper = file_path == group.keep
                child = QTreeWidgetItem([file_path, human_size(group.size), "keep" if is_keeper else "duplicate"])
                _set_all_tooltips(child)
                if not is_keeper:
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    child.setCheckState(0, Qt.CheckState.Unchecked)
                parent.addChild(child)
            parent.setExpanded(True)

    def _trash_checked(self) -> None:
        to_trash: list[str] = []
        for i in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.flags() & Qt.ItemFlag.ItemIsUserCheckable and child.checkState(0) == Qt.CheckState.Checked:
                    to_trash.append(child.text(0))

        if not to_trash:
            QMessageBox.information(self, "Nothing selected", "Check at least one duplicate copy first.")
            return

        confirm = QMessageBox.question(
            self,
            "Confirm",
            f"Send {len(to_trash)} file(s) to the trash? This can be undone from your OS trash bin.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        failures = []
        for path in to_trash:
            try:
                trash_file(path)
            except OSError as exc:
                failures.append(f"{path}: {exc}")

        if failures:
            QMessageBox.warning(self, "Some files could not be trashed", "\n".join(failures))
        self.update_results(self._rebuild_after_trash(to_trash))

    def _rebuild_after_trash(self, trashed: list[str]) -> list[DuplicateGroup]:
        rebuilt = []
        for group in self._groups:
            remaining = [f for f in group.files if f not in trashed]
            if len(remaining) >= 2:
                rebuilt.append(
                    DuplicateGroup(file_hash=group.file_hash, size=group.size, files=remaining, keep=group.keep)
                )
        return rebuilt
