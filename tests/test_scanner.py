from storage_ai.scanner import scan_directory


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
