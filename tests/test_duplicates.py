import pytest

from storage_ai.duplicates import find_duplicates
from storage_ai.exceptions import ScanCancelled
from storage_ai.scanner import scan_directory


def test_identical_files_are_grouped(tmp_path):
    content = "x" * 5000  # above MIN_DUPLICATE_SIZE_BYTES
    (tmp_path / "a.txt").write_text(content)
    (tmp_path / "b.txt").write_text(content)
    (tmp_path / "unique.txt").write_text("y" * 5000)

    records = scan_directory(tmp_path)
    groups = find_duplicates(records)

    assert len(groups) == 1
    assert set(groups[0].files) == {str(tmp_path / "a.txt"), str(tmp_path / "b.txt")}
    assert groups[0].wasted_space == 5000


def test_same_size_different_content_not_grouped(tmp_path):
    (tmp_path / "a.txt").write_text("a" * 5000)
    (tmp_path / "b.txt").write_text("b" * 5000)

    records = scan_directory(tmp_path)
    groups = find_duplicates(records)

    assert groups == []


def test_small_files_ignored_by_default_threshold(tmp_path):
    (tmp_path / "a.txt").write_text("tiny")
    (tmp_path / "b.txt").write_text("tiny")

    records = scan_directory(tmp_path)
    groups = find_duplicates(records)

    assert groups == []


def test_keeper_is_the_oldest_copy(tmp_path):
    content = "z" * 5000
    older = tmp_path / "older.txt"
    newer = tmp_path / "newer.txt"
    older.write_text(content)
    newer.write_text(content)

    records = scan_directory(tmp_path)
    # Force a clear creation-time ordering regardless of filesystem timing.
    for record in records:
        if record.path == str(older):
            record.created_time = 100.0
        else:
            record.created_time = 200.0

    groups = find_duplicates(records)

    assert groups[0].keep == str(older)


def test_find_duplicates_respects_cancellation(tmp_path):
    content = "x" * 5000
    (tmp_path / "a.txt").write_text(content)
    (tmp_path / "b.txt").write_text(content)

    records = scan_directory(tmp_path)

    with pytest.raises(ScanCancelled):
        find_duplicates(records, cancel_check=lambda: True)
