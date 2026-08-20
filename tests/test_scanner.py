import pytest

from storage_ai.exceptions import ScanCancelled
from storage_ai.scanner import _should_prune_dir, count_files, scan_directory


def test_scan_finds_all_files(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.txt").write_text("world")

    records = scan_directory(tmp_path)

    paths = {r.path for r in records}
    assert str(tmp_path / "a.txt") in paths
    assert str(nested / "b.txt") in paths
    assert len(records) == 2


def test_scan_excludes_configured_directories(tmp_path):
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    (excluded / "dep.js").write_text("noise")
    (tmp_path / "keep.py").write_text("code")

    records = scan_directory(tmp_path)

    assert len(records) == 1
    assert records[0].path.endswith("keep.py")


def test_scan_records_size_and_extension(tmp_path):
    (tmp_path / "data.csv").write_text("a,b,c\n1,2,3\n")

    [record] = scan_directory(tmp_path)

    assert record.extension == ".csv"
    assert record.size == len("a,b,c\n1,2,3\n")


def test_prune_virtual_fs_root_at_actual_root():
    assert _should_prune_dir("/", "proc", set()) is True
    assert _should_prune_dir("/", "sys", set()) is True
    assert _should_prune_dir("/", "dev", set()) is True
    assert _should_prune_dir("/", "run", set()) is True


def test_does_not_prune_a_folder_that_merely_shares_a_name():
    # A project can legitimately have a subfolder literally named "proc"
    # (e.g. a Linux kernel source tree) -- only the true root-level virtual
    # filesystem should ever be pruned.
    assert _should_prune_dir("/home/user/kernel/fs", "proc", set()) is False


def test_prune_still_honors_the_name_exclude_set():
    assert _should_prune_dir("/home/user/project", "node_modules", {"node_modules"}) is True
    assert _should_prune_dir("/home/user/project", "src", {"node_modules"}) is False


def test_count_files_matches_scan_directory(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "b.txt").write_text("world")
    excluded = tmp_path / "node_modules"
    excluded.mkdir()
    (excluded / "dep.js").write_text("noise")

    assert count_files(tmp_path) == len(scan_directory(tmp_path)) == 2


def test_count_files_respects_cancellation(tmp_path):
    (tmp_path / "a.txt").write_text("hello")

    with pytest.raises(ScanCancelled):
        count_files(tmp_path, cancel_check=lambda: True)


def test_scan_directory_respects_cancellation(tmp_path):
    (tmp_path / "a.txt").write_text("hello")

    with pytest.raises(ScanCancelled):
        scan_directory(tmp_path, cancel_check=lambda: True)


def test_scan_directory_progress_reports_final_count(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x")

    seen = []
    scan_directory(tmp_path, on_progress=seen.append, progress_interval=2)

    assert seen[-1] == 5
