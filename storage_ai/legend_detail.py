"""Turns an aggregated chart/legend total (a category's bytes, a file
type's bytes, a cluster's files) back into the actual directories behind
it, so an info dialog can answer "what's actually in this number," not
just restate it in different units. Pure logic, no Qt -- unit-testable
like everything else non-GUI in this app, and reused by every chart tab
that aggregates many files into one legend row (dashboard's category box,
File Types, Folders, Clusters).
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Iterable

from storage_ai.utils import human_size

_DEFAULT_TOP_N = 5


def directory_totals(paths_and_sizes: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Groups by immediate parent directory (not the file's own path) --
    e.g. 200 log files in the same folder collapse into one entry instead
    of 200, which is what makes this actually readable in a dialog."""
    totals: dict[str, int] = defaultdict(int)
    for path, size in paths_and_sizes:
        totals[os.path.dirname(path) or "/"] += size
    return dict(totals)


def format_directory_breakdown(paths_and_sizes: Iterable[tuple[str, int]], top_n: int = _DEFAULT_TOP_N) -> str:
    """Human-readable lines for the top_n contributing directories by
    size, largest first. Explicitly says so, rather than silently
    truncating, when there are more than top_n -- a total that came from
    50 directories shouldn't look like it only came from 5."""
    totals = directory_totals(paths_and_sizes)
    if not totals:
        return "  (no contributing files found)"

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    lines = [f"  {path}  --  {human_size(total)}" for path, total in ranked[:top_n]]
    remaining = len(ranked) - top_n
    if remaining > 0:
        lines.append(f"  ...and {remaining} more director{'y' if remaining == 1 else 'ies'}")
    return "\n".join(lines)
