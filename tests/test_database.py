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
