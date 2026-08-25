from storage_ai import database
from storage_ai.models import FileEvent
from storage_ai.watcher_service import _ALERT_COOLDOWN_SECONDS, _check_trends


def test_check_trends_records_alert_and_applies_cooldown(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    now = 1000.0
    for i in range(25):
        database.record_file_event(
            FileEvent(
                timestamp=now,
                path=f"/f{i}",
                event_type="deleted",
                size=None,
                uid=1000,
                username="bob",
                attribution_source="stat",
            ),
            db_path=db_path,
        )

    recent_alert_keys: dict = {}
    _check_trends(now, recent_alert_keys, db_path=db_path)

    alerts = database.get_recent_alerts(since=0.0, db_path=db_path)
    assert any(a["alert_type"] == "rapid_deletes" and a["username"] == "bob" for a in alerts)

    # Firing again immediately (within the cooldown) must not duplicate the alert.
    _check_trends(now + 1, recent_alert_keys, db_path=db_path)
    alerts_after = database.get_recent_alerts(since=0.0, db_path=db_path)
    assert len(alerts_after) == len(alerts)

    # After the cooldown elapses, a *fresh* burst can fire again -- note this
    # needs new events at the later timestamp, since the original burst has
    # by now aged out of the (much shorter) detection window itself.
    later = now + _ALERT_COOLDOWN_SECONDS + 1
    for i in range(25):
        database.record_file_event(
            FileEvent(
                timestamp=later,
                path=f"/g{i}",
                event_type="deleted",
                size=None,
                uid=1000,
                username="bob",
                attribution_source="stat",
            ),
            db_path=db_path,
        )
    _check_trends(later, recent_alert_keys, db_path=db_path)
    alerts_final = database.get_recent_alerts(since=0.0, db_path=db_path)
    assert len(alerts_final) > len(alerts)


def test_check_trends_is_a_noop_with_no_events(tmp_path):
    db_path = tmp_path / "test.sqlite3"

    _check_trends(1000.0, {}, db_path=db_path)  # should not raise

    assert database.get_recent_alerts(since=0.0, db_path=db_path) == []
