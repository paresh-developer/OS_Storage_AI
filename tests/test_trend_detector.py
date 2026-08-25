from storage_ai.models import FileEvent
from storage_ai.trend_detector import (
    BURST_EVENT_COUNT,
    LARGE_FILE_BYTES,
    RAPID_DELETE_COUNT,
    RAPID_MODIFY_COUNT,
    detect_alerts,
)


def _event(username, event_type, timestamp, size=1000, path="/x"):
    return FileEvent(
        timestamp=timestamp,
        path=path,
        event_type=event_type,
        size=size,
        uid=1000,
        username=username,
        attribution_source="stat",
    )


def test_large_file_added_triggers_alert():
    events = [_event("alice", "created", 0, size=LARGE_FILE_BYTES + 1)]

    alerts = detect_alerts(events, now=0)

    assert any(a.alert_type == "large_file_added" and a.username == "alice" for a in alerts)


def test_small_file_added_does_not_trigger_alert():
    events = [_event("alice", "created", 0, size=1000)]

    alerts = detect_alerts(events, now=0)

    assert not any(a.alert_type == "large_file_added" for a in alerts)


def test_rapid_deletes_by_one_user_triggers_alert():
    events = [_event("bob", "deleted", 0, path=f"/f{i}") for i in range(RAPID_DELETE_COUNT)]

    alerts = detect_alerts(events, now=0)

    rapid = [a for a in alerts if a.alert_type == "rapid_deletes"]
    assert len(rapid) == 1
    assert rapid[0].username == "bob"


def test_deletes_below_threshold_do_not_trigger():
    events = [_event("bob", "deleted", 0, path=f"/f{i}") for i in range(RAPID_DELETE_COUNT - 1)]

    alerts = detect_alerts(events, now=0)

    assert not any(a.alert_type == "rapid_deletes" for a in alerts)


def test_rapid_deletes_outside_window_do_not_count():
    old_events = [_event("bob", "deleted", -1000, path=f"/f{i}") for i in range(RAPID_DELETE_COUNT)]

    alerts = detect_alerts(old_events, now=0)

    assert not any(a.alert_type == "rapid_deletes" for a in alerts)


def test_rapid_modifications_by_one_user_triggers_alert():
    events = [_event("carol", "modified", 0, path=f"/f{i}") for i in range(RAPID_MODIFY_COUNT)]

    alerts = detect_alerts(events, now=0)

    assert any(a.alert_type == "rapid_modifications" and a.username == "carol" for a in alerts)


def test_burst_activity_mixed_event_types():
    events = (
        [_event("dave", "created", 0, path=f"/c{i}") for i in range(BURST_EVENT_COUNT // 2)]
        + [_event("dave", "modified", 0, path=f"/m{i}") for i in range(BURST_EVENT_COUNT // 2)]
    )

    alerts = detect_alerts(events, now=0)

    assert any(a.alert_type == "burst_activity" and a.username == "dave" for a in alerts)


def test_different_users_are_tracked_independently():
    events = [_event("bob", "deleted", 0, path=f"/b{i}") for i in range(RAPID_DELETE_COUNT)]
    events += [_event("alice", "deleted", 0, path="/a0")]  # well below threshold

    alerts = detect_alerts(events, now=0)

    rapid_usernames = {a.username for a in alerts if a.alert_type == "rapid_deletes"}
    assert rapid_usernames == {"bob"}


def test_no_events_produces_no_alerts():
    assert detect_alerts([], now=0) == []
