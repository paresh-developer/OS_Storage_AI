from storage_ai import database
from storage_ai.audit_log import AuditFileEvent
from storage_ai.models import ActivityAlert, FileEvent


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


def _file_event(path="/srv/a.txt", event_type="created", timestamp=100.0, size=1000, username="alice"):
    return FileEvent(
        timestamp=timestamp,
        path=path,
        event_type=event_type,
        size=size,
        uid=1000,
        username=username,
        attribution_source="stat",
    )


def test_record_and_retrieve_file_events(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_file_event(_file_event(timestamp=100.0), db_path=db_path)
    database.record_file_event(_file_event(timestamp=200.0, path="/srv/b.txt"), db_path=db_path)

    recent = database.get_recent_file_events(since=150.0, db_path=db_path)

    assert len(recent) == 1
    assert recent[0]["path"] == "/srv/b.txt"


def test_get_recent_file_events_orders_most_recent_first(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_file_event(_file_event(timestamp=100.0, path="/a"), db_path=db_path)
    database.record_file_event(_file_event(timestamp=300.0, path="/c"), db_path=db_path)
    database.record_file_event(_file_event(timestamp=200.0, path="/b"), db_path=db_path)

    recent = database.get_recent_file_events(since=0.0, db_path=db_path)

    assert [r["path"] for r in recent] == ["/c", "/b", "/a"]


def test_upgrade_event_attribution_matches_by_path_and_close_timestamp(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_file_event(
        _file_event(path="/srv/shared/report.txt", timestamp=1000.0, username=None), db_path=db_path
    )
    audit_event = AuditFileEvent(
        timestamp=1000.2, path="/srv/shared/report.txt", event_type="created", username="alice", pid=42, process_name="vim"
    )

    updated = database.upgrade_event_attribution(audit_event, db_path=db_path)

    assert updated is True
    [row] = database.get_recent_file_events(since=0.0, db_path=db_path)
    assert row["username"] == "alice"
    assert row["attribution_source"] == "audit"
    assert row["pid"] == 42
    assert row["process_name"] == "vim"


def test_upgrade_event_attribution_ignores_distant_timestamps(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_file_event(_file_event(path="/srv/report.txt", timestamp=1000.0), db_path=db_path)
    audit_event = AuditFileEvent(
        timestamp=1100.0, path="/srv/report.txt", event_type="created", username="alice", pid=1, process_name="x"
    )

    updated = database.upgrade_event_attribution(audit_event, tolerance_seconds=5.0, db_path=db_path)

    assert updated is False


def test_record_and_retrieve_alerts(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    alert = ActivityAlert(timestamp=100.0, alert_type="rapid_deletes", username="bob", detail="20 files deleted", severity="warning")
    database.record_alert(alert, db_path=db_path)

    recent = database.get_recent_alerts(since=0.0, db_path=db_path)

    assert len(recent) == 1
    assert recent[0]["alert_type"] == "rapid_deletes"
    assert recent[0]["username"] == "bob"


def test_user_activity_summary_aggregates_correctly(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database.record_file_event(_file_event(username="alice", event_type="created", size=1000, path="/a"), db_path=db_path)
    database.record_file_event(_file_event(username="alice", event_type="modified", size=500, path="/b"), db_path=db_path)
    database.record_file_event(_file_event(username="bob", event_type="deleted", size=None, path="/c"), db_path=db_path)

    summary = {row["username"]: row for row in database.get_user_activity_summary(since=0.0, db_path=db_path)}

    assert summary["alice"]["event_count"] == 2
    assert summary["alice"]["bytes_added"] == 1500
    assert summary["alice"]["created_count"] == 1
    assert summary["alice"]["modified_count"] == 1
    assert summary["bob"]["deleted_count"] == 1
    assert summary["bob"]["bytes_added"] == 0
