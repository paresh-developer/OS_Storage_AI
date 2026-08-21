"""Tests for the click-a-legend-row-to-highlight interaction shared by the
four chart tabs. Runs headless (QT_QPA_PLATFORM=offscreen is set by the
test session config, not here) since these are Qt widgets, but no display
or event loop is needed -- the tabs' own methods are called directly."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from storage_ai.clustering import ClusteringResult, ClusterPoint, ClusterSummary
from storage_ai.gui.chart_tab import make_color_icon
from storage_ai.gui.clusters_tab import ClustersTab
from storage_ai.gui.file_types_tab import FileTypesTab
from storage_ai.gui.folders_tab import FoldersTab
from storage_ai.gui.forecast_tab import ForecastTab
from storage_ai.models import FileRecord, StorageForecast
from storage_ai.pipeline import AnalysisResult


def _icon_center_color(icon):
    image = icon.pixmap(14, 14).toImage()
    return image.pixelColor(7, 7)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _forecast():
    return StorageForecast(
        current_total_bytes=10_000,
        free_bytes=90_000,
        bytes_per_day=100.0,
        days_until_full=900.0,
        projected_30_day_bytes=13_000,
        history_source="file-timestamps",
    )


def _analysis_result(records, clustering=None):
    return AnalysisResult(
        root="/demo",
        records=records,
        duplicate_groups=[],
        unused_candidates=[],
        forecast=_forecast(),
        recommendations=[],
        clustering=clustering,
        category_totals={},
    )


def _records():
    return [
        FileRecord("/demo/a.txt", 5000, ".txt", 0, 0, 0, 0),
        FileRecord("/demo/b.jpg", 3000, ".jpg", 0, 0, 0, 0),
        FileRecord("/demo/c.jpg", 2000, ".jpg", 0, 0, 0, 0),
    ]


def test_file_types_tab_click_highlights_and_toggles_off():
    tab = FileTypesTab()
    tab.update_results(_analysis_result(_records()))

    assert tab._legend_list.count() == 2  # .jpg (grouped) and .txt
    first_item = tab._legend_list.item(0)

    tab._on_item_clicked(first_item)
    alphas_selected = [w.get_alpha() for w in tab._wedges]
    assert alphas_selected[0] == 1.0
    assert any(a != 1.0 for a in alphas_selected[1:])

    tab._on_item_clicked(first_item)  # click again -> toggles off
    assert tab._selected_row is None
    assert all(w.get_alpha() == 1.0 for w in tab._wedges)


def test_clear_selection_button_resets_highlight_and_disables_itself():
    tab = FileTypesTab()
    tab.update_results(_analysis_result(_records()))

    assert tab._clear_button.isEnabled() is False

    tab._on_item_clicked(tab._legend_list.item(0))
    assert tab._clear_button.isEnabled() is True
    assert tab._selected_row == 0

    tab._clear_selection_clicked()
    assert tab._selected_row is None
    assert tab._clear_button.isEnabled() is False
    assert all(w.get_alpha() == 1.0 for w in tab._wedges)


def test_clear_selection_button_is_a_noop_when_nothing_selected():
    tab = FileTypesTab()
    tab.update_results(_analysis_result(_records()))

    tab._clear_selection_clicked()  # should not raise
    assert tab._selected_row is None


@pytest.mark.parametrize(
    "tab_cls",
    [FileTypesTab, ForecastTab, FoldersTab, ClustersTab],
)
def test_every_chart_tab_has_info_button_and_tooltips(tab_cls):
    tab = tab_cls()

    assert tab._info_button.toolTip()
    assert tab._info_title
    assert tab._info_details
    assert tab._canvas.toolTip()
    assert tab._legend_list.toolTip()
    assert tab._clear_button.toolTip()


def test_reset_selection_disables_clear_button_too():
    tab = FileTypesTab()
    tab.update_results(_analysis_result(_records()))
    tab._on_item_clicked(tab._legend_list.item(0))
    assert tab._clear_button.isEnabled() is True

    tab.update_results(_analysis_result(_records()))
    assert tab._clear_button.isEnabled() is False


def test_forecast_tab_click_highlights_one_line():
    tab = ForecastTab()
    tab.update_results(_analysis_result(_records()))

    assert tab._legend_list.count() == 2
    tab._on_item_clicked(tab._legend_list.item(1))

    assert tab._lines[1].get_alpha() == 1.0
    assert tab._lines[0].get_alpha() < 1.0


def test_folders_tab_click_highlights_one_rect():
    tab = FoldersTab()
    tab.update_results(_analysis_result(_records()))

    assert tab._legend_list.count() >= 1
    tab._on_item_clicked(tab._legend_list.item(0))

    assert tab._patches[0].get_alpha() == 1.0
    if len(tab._patches) > 1:
        assert any(p.get_alpha() != 1.0 for p in tab._patches[1:])


def test_clusters_tab_click_highlights_one_cluster():
    points = [
        ClusterPoint(path="/demo/a.txt", size=5000, days_since_access=1, cluster_id=0),
        ClusterPoint(path="/demo/b.jpg", size=3000, days_since_access=400, cluster_id=1),
    ]
    summaries = [
        ClusterSummary(cluster_id=0, label="Small & Active", file_count=1, total_size=5000, median_size=5000, median_days_since_access=1),
        ClusterSummary(cluster_id=1, label="Small & Stale", file_count=1, total_size=3000, median_size=3000, median_days_since_access=400),
    ]
    clustering = ClusteringResult(points=points, summaries=summaries)

    tab = ClustersTab()
    tab.update_results(_analysis_result(_records(), clustering=clustering))

    assert tab._legend_list.count() == 2
    tab._on_item_clicked(tab._legend_list.item(0))

    assert tab._collections[0].get_alpha() == pytest.approx(0.7)
    assert tab._collections[1].get_alpha() < 0.7


def test_clusters_tab_handles_no_clustering_result_gracefully():
    tab = ClustersTab()
    tab.update_results(_analysis_result(_records(), clustering=None))

    assert tab._legend_list.count() == 0
    assert tab._collections == []


def test_reset_selection_clears_stale_state_across_rescans():
    tab = FileTypesTab()
    tab.update_results(_analysis_result(_records()))
    tab._on_item_clicked(tab._legend_list.item(0))
    assert tab._selected_row == 0

    tab.update_results(_analysis_result(_records()))
    assert tab._selected_row is None
    assert tab._legend_list.currentRow() == -1


def test_make_color_icon_accepts_hex_string():
    icon = make_color_icon("#ff0000")
    color = _icon_center_color(icon)
    assert (color.red(), color.green(), color.blue()) == (255, 0, 0)


def test_make_color_icon_accepts_rgba_float_tuple():
    icon = make_color_icon((0.0, 1.0, 0.0, 1.0))
    color = _icon_center_color(icon)
    assert (color.red(), color.green(), color.blue()) == (0, 255, 0)


def test_make_color_icon_accepts_rgb_without_alpha():
    icon = make_color_icon((0.0, 0.0, 1.0))
    color = _icon_center_color(icon)
    assert (color.red(), color.green(), color.blue()) == (0, 0, 255)


def test_file_types_legend_icons_match_rendered_wedge_colors():
    tab = FileTypesTab()
    tab.update_results(_analysis_result(_records()))

    for row in range(tab._legend_list.count()):
        item = tab._legend_list.item(row)
        assert not item.icon().isNull()
        expected = tab._wedges[row].get_facecolor()
        icon_color = _icon_center_color(item.icon())
        assert icon_color.redF() == pytest.approx(expected[0], abs=0.02)
        assert icon_color.greenF() == pytest.approx(expected[1], abs=0.02)
        assert icon_color.blueF() == pytest.approx(expected[2], abs=0.02)


def test_forecast_legend_icons_match_line_colors():
    tab = ForecastTab()
    tab.update_results(_analysis_result(_records()))

    for row, line in enumerate(tab._lines):
        item = tab._legend_list.item(row)
        assert not item.icon().isNull()


def test_folders_legend_icons_are_non_null():
    tab = FoldersTab()
    tab.update_results(_analysis_result(_records()))

    for row in range(tab._legend_list.count()):
        assert not tab._legend_list.item(row).icon().isNull()


def test_clusters_legend_icons_are_non_null():
    points = [ClusterPoint(path="/demo/a.txt", size=5000, days_since_access=1, cluster_id=0)]
    summaries = [
        ClusterSummary(cluster_id=0, label="Small & Active", file_count=1, total_size=5000, median_size=5000, median_days_since_access=1)
    ]
    clustering = ClusteringResult(points=points, summaries=summaries)

    tab = ClustersTab()
    tab.update_results(_analysis_result(_records(), clustering=clustering))

    assert not tab._legend_list.item(0).icon().isNull()
