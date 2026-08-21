"""Test session config: force Qt's offscreen platform plugin so the GUI
tests (test_chart_tabs.py) run consistently without a real display, whether
in this dev environment or a headless CI runner. Must be set before PySide6
is imported anywhere, which pytest guarantees by loading conftest.py first.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
