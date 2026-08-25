from __future__ import annotations

from storage_ai.legend_detail import directory_totals, format_directory_breakdown


def test_directory_totals_groups_by_parent_directory():
    totals = directory_totals(
        [
            ("/var/log/app/a.log", 100),
            ("/var/log/app/b.log", 200),
            ("/var/log/other/c.log", 50),
        ]
    )

    assert totals == {"/var/log/app": 300, "/var/log/other": 50}


def test_directory_totals_empty_input():
    assert directory_totals([]) == {}


def test_format_directory_breakdown_orders_largest_first():
    text = format_directory_breakdown(
        [
            ("/a/x.txt", 100),
            ("/b/y.txt", 900),
        ]
    )

    lines = text.splitlines()
    assert lines[0].startswith("  /b")
    assert lines[1].startswith("  /a")


def test_format_directory_breakdown_reports_nothing_found():
    assert "no contributing files found" in format_directory_breakdown([])


def test_format_directory_breakdown_truncates_with_explicit_count():
    items = [(f"/dir{i}/f.txt", 1) for i in range(8)]
    text = format_directory_breakdown(items, top_n=3)

    lines = text.splitlines()
    assert len(lines) == 4  # 3 directories + the "...and N more" line
    assert "...and 5 more directories" in lines[-1]


def test_format_directory_breakdown_singular_remaining_directory():
    items = [(f"/dir{i}/f.txt", 1) for i in range(4)]
    text = format_directory_breakdown(items, top_n=3)

    assert "...and 1 more directory" in text.splitlines()[-1]


def test_format_directory_breakdown_no_truncation_note_when_exact():
    items = [(f"/dir{i}/f.txt", 1) for i in range(3)]
    text = format_directory_breakdown(items, top_n=3)

    assert "more director" not in text
    assert len(text.splitlines()) == 3
