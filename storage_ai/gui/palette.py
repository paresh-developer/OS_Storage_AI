"""Shared chart color constants -- fixed categorical order from the
validated reference palette (dataviz skill, references/palette.md).
Adjacent-pair CVD-safe for up to all 8 slots, which covers the treemap's
folder categories. A scatter plot must compare every pair of series, not
just adjacent ones, and only the first 3 slots clear that stricter
all-pairs bar -- so the cluster chart is capped there (see clustering.py's
matching max_clusters=3 default)."""

from __future__ import annotations

CATEGORICAL_PALETTE = [
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
]
MUTED_OTHER = "#898781"
SCATTER_SAFE_PALETTE = CATEGORICAL_PALETTE[:3]
