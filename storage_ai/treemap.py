"""Squarified treemap layout (Bruls, Huizing & van Wijk, 1999).

Lays out a list of (label, value) items as nested rectangles whose area is
proportional to value, while keeping each rectangle close to square rather
than a long sliver -- which is what makes a treemap readable at a glance.
No plotting library ships a treemap primitive, so this is a small,
self-contained implementation of the published algorithm; rendering is
done separately (see gui/folders_tab.py) with plain matplotlib patches.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TreemapRect:
    label: str
    value: float
    x: float
    y: float
    width: float
    height: float


def compute_treemap(
    items: list[tuple[str, float]],
    width: float = 1.0,
    height: float = 1.0,
) -> list[TreemapRect]:
    """`items` should already be sorted descending by value for the
    squarify algorithm to produce good aspect ratios."""
    positive_items = [(label, value) for label, value in items if value > 0]
    if not positive_items:
        return []

    labels = [label for label, _ in positive_items]
    values = [float(value) for _, value in positive_items]
    normalized = _normalize(values, width, height)

    boxes = _squarify(normalized, 0.0, 0.0, width, height)
    return [
        TreemapRect(label=label, value=value, x=box[0], y=box[1], width=box[2], height=box[3])
        for label, value, box in zip(labels, values, boxes)
    ]


def _normalize(values: list[float], width: float, height: float) -> list[float]:
    total = sum(values)
    scale = (width * height) / total
    return [v * scale for v in values]


def _layout_row(sizes: list[float], x: float, y: float, height: float) -> list[tuple[float, float, float, float]]:
    row_width = sum(sizes) / height
    boxes = []
    cursor = y
    for size in sizes:
        box_height = size / row_width
        boxes.append((x, cursor, row_width, box_height))
        cursor += box_height
    return boxes


def _layout_col(sizes: list[float], x: float, y: float, width: float) -> list[tuple[float, float, float, float]]:
    col_height = sum(sizes) / width
    boxes = []
    cursor = x
    for size in sizes:
        box_width = size / col_height
        boxes.append((cursor, y, box_width, col_height))
        cursor += box_width
    return boxes


def _worst_aspect_ratio(sizes: list[float], x: float, y: float, width: float, height: float) -> float:
    boxes = _layout_row(sizes, x, y, height) if width >= height else _layout_col(sizes, x, y, width)
    return max(max(w / h, h / w) for _, _, w, h in boxes)


def _squarify(
    sizes: list[float], x: float, y: float, width: float, height: float
) -> list[tuple[float, float, float, float]]:
    if not sizes:
        return []
    if len(sizes) == 1:
        return _layout_row(sizes, x, y, height) if width >= height else _layout_col(sizes, x, y, width)

    split = 1
    while split < len(sizes) and _worst_aspect_ratio(sizes[:split], x, y, width, height) >= _worst_aspect_ratio(
        sizes[: split + 1], x, y, width, height
    ):
        split += 1

    current, remaining = sizes[:split], sizes[split:]

    if width >= height:
        boxes = _layout_row(current, x, y, height)
        covered_width = sum(current) / height
        leftover = (x + covered_width, y, width - covered_width, height)
    else:
        boxes = _layout_col(current, x, y, width)
        covered_height = sum(current) / width
        leftover = (x, y + covered_height, width, height - covered_height)

    return boxes + _squarify(remaining, *leftover)
