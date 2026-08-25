from storage_ai.models import file_event_from_row


def test_file_event_from_row_round_trips_all_fields():
    row = {
        "timestamp": 100.0,
        "path": "/a",
        "event_type": "created",
        "size": 500,
        "uid": 1000,
        "username": "alice",
        "attribution_source": "stat",
        "pid": None,
        "process_name": None,
    }

    event = file_event_from_row(row)

    assert event.timestamp == 100.0
    assert event.path == "/a"
    assert event.event_type == "created"
    assert event.size == 500
    assert event.uid == 1000
    assert event.username == "alice"
    assert event.attribution_source == "stat"
    assert event.pid is None
    assert event.process_name is None
