import pytest

from storage_ai.treemap import compute_treemap


def test_single_item_fills_the_whole_rect():
    [rect] = compute_treemap([("only", 100)], width=10, height=5)
    assert rect.x == 0 and rect.y == 0
    assert rect.width == pytest.approx(10)
    assert rect.height == pytest.approx(5)


def test_total_area_is_conserved():
    items = [("a", 500), ("b", 300), ("c", 150), ("d", 50)]
    rects = compute_treemap(items, width=20, height=10)

    total_area = sum(r.width * r.height for r in rects)
    assert total_area == pytest.approx(200, rel=1e-6)


def test_areas_proportional_to_values():
    items = [("big", 800), ("small", 200)]
    rects = compute_treemap(items, width=10, height=10)

    by_label = {r.label: r for r in rects}
    assert by_label["big"].width * by_label["big"].height == pytest.approx(80, rel=1e-6)
    assert by_label["small"].width * by_label["small"].height == pytest.approx(20, rel=1e-6)


def test_zero_and_negative_values_are_dropped():
    items = [("a", 100), ("b", 0), ("c", -5)]
    rects = compute_treemap(items, width=10, height=10)

    assert {r.label for r in rects} == {"a"}


def test_empty_input_returns_empty_list():
    assert compute_treemap([], width=10, height=10) == []


def test_rectangles_do_not_overlap():
    items = [("a", 40), ("b", 30), ("c", 20), ("d", 10)]
    rects = compute_treemap(items, width=10, height=10)

    for i, r1 in enumerate(rects):
        for r2 in rects[i + 1 :]:
            horizontal_gap = r1.x + r1.width <= r2.x + 1e-9 or r2.x + r2.width <= r1.x + 1e-9
            vertical_gap = r1.y + r1.height <= r2.y + 1e-9 or r2.y + r2.height <= r1.y + 1e-9
            assert horizontal_gap or vertical_gap
