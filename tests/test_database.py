from storage_ai import database


def test_record_and_retrieve_snapshot(tmp_path):
    db_path = tmp_path / "test.sqlite3"

    database.record_snapshot(
        root_path="/home/user",
        total_size=1000,
        file_count=5,
        free_bytes=9000,
        extension_totals={".txt": (600, 3), ".jpg": (400, 2)},
        db_path=db_path,
        taken_at=123.0,
    )

    snapshots = database.get_snapshots("/home/user", db_path=db_path)

    assert len(snapshots) == 1
    assert snapshots[0]["total_size"] == 1000
    assert snapshots[0]["taken_at"] == 123.0


def test_snapshots_are_scoped_by_root_path(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_snapshot("/a", 100, 1, 900, {}, db_path=db_path, taken_at=1.0)
    database.record_snapshot("/b", 200, 2, 800, {}, db_path=db_path, taken_at=2.0)

    assert len(database.get_snapshots("/a", db_path=db_path)) == 1
    assert len(database.get_snapshots("/b", db_path=db_path)) == 1


def test_action_log_records_entries(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.log_action("trash", "/a/file.txt", 500, detail="test", db_path=db_path)

    actions = database.get_actions(db_path=db_path)

    assert len(actions) == 1
    assert actions[0]["action_type"] == "trash"
    assert actions[0]["path"] == "/a/file.txt"


def test_recent_roots_most_recent_first(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_snapshot("/a", 100, 1, 900, {}, db_path=db_path, taken_at=1.0)
    database.record_snapshot("/b", 200, 2, 800, {}, db_path=db_path, taken_at=2.0)
    database.record_snapshot("/c", 300, 3, 700, {}, db_path=db_path, taken_at=3.0)

    recent = database.get_recent_roots(db_path=db_path)

    assert [r["root_path"] for r in recent] == ["/c", "/b", "/a"]


def test_recent_roots_deduplicates_and_uses_latest_scan(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_snapshot("/a", 100, 1, 900, {}, db_path=db_path, taken_at=1.0)
    database.record_snapshot("/a", 500, 9, 900, {}, db_path=db_path, taken_at=5.0)

    recent = database.get_recent_roots(db_path=db_path)

    assert len(recent) == 1
    assert recent[0]["total_size"] == 500
    assert recent[0]["file_count"] == 9
    assert recent[0]["taken_at"] == 5.0


def test_recent_roots_respects_limit(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    for i in range(5):
        database.record_snapshot(f"/root{i}", 100, 1, 900, {}, db_path=db_path, taken_at=float(i))

    assert len(database.get_recent_roots(limit=2, db_path=db_path)) == 2


def test_clear_scan_history_removes_snapshots_and_breakdowns(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_snapshot(
        "/a", 100, 1, 900, {".txt": (100, 1)}, db_path=db_path, taken_at=1.0
    )
    database.log_action("trash", "/a/old.txt", 50, db_path=db_path)

    database.clear_scan_history(db_path=db_path)

    assert database.get_recent_roots(db_path=db_path) == []
    assert database.get_snapshots("/a", db_path=db_path) == []
    # the action audit log is a separate history and must survive.
    assert len(database.get_actions(db_path=db_path)) == 1
