"""Test session config: force Qt's offscreen platform plugin so the GUI
tests (test_chart_tabs.py) run consistently without a real display, whether
in this dev environment or a headless CI runner. Must be set before PySide6
is imported anywhere, which pytest guarantees by loading conftest.py first.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _no_blocking_dialogs(monkeypatch):
    """Safety net, not a workaround for a specific test: QDialog.exec()
    opens a real modal event loop that only returns once a human clicks a
    button -- QMessageBox's static helpers (.information/.warning/etc.)
    are built on it too. In a headless test run there's no human, so any
    test that triggers one without its own mock hangs forever rather than
    failing fast. This happened for real: swapping a direct
    QMessageBox.information call for show_info_dialog() (see
    gui/info_dialog.py) silently broke a test that mocked the old call by
    name, and the suite hung for minutes before anyone noticed. Defaulting
    exec() to a no-op "accepted" return makes any future case like this a
    fast, visible failure instead -- and it's a no-op for every test that
    already mocks its own dialog call directly, since that mock is what
    actually runs instead of ever reaching a real exec()."""
    monkeypatch.setattr("PySide6.QtWidgets.QDialog.exec", lambda self: 1)
