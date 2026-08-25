"""Rate-based trend/anomaly detection over a stream of file events.

Plain threshold rules, not a black-box model -- consistent with the rest
of the app's recommendation style, and easy to justify to a server admin
("why did this fire?") in exactly the terms it fired in.
"""

from __future__ import annotations

import time
from collections import defaultdict

from storage_ai.models import ActivityAlert, FileEvent
from storage_ai.utils import human_size

LARGE_FILE_BYTES = 500 * 1024 * 1024  # 500 MB
RAPID_DELETE_COUNT = 20
RAPID_DELETE_WINDOW_SECONDS = 60
RAPID_MODIFY_COUNT = 30
RAPID_MODIFY_WINDOW_SECONDS = 60
BURST_EVENT_COUNT = 100
BURST_WINDOW_SECONDS = 60


def detect_alerts(events: list[FileEvent], now: float | None = None) -> list[ActivityAlert]:
    """`events` should include at least everything from the widest window
    used below (BURST_WINDOW_SECONDS). Returns every alert whose condition
    currently holds -- callers are responsible for not re-alerting on the
    same condition every time they poll (see watcher_service.py's
    cooldown tracking)."""
    now = time.time() if now is None else now
    alerts: list[ActivityAlert] = []

    for event in events:
        if event.event_type in ("created", "modified") and event.size and event.size >= LARGE_FILE_BYTES:
            alerts.append(
                ActivityAlert(
                    timestamp=event.timestamp,
                    alert_type="large_file_added",
                    username=event.username,
                    detail=f"{event.path} ({human_size(event.size)})",
                    severity="info",
                )
            )

    alerts.extend(
        _rate_alerts(events, now, "deleted", RAPID_DELETE_WINDOW_SECONDS, RAPID_DELETE_COUNT, "rapid_deletes", "warning")
    )
    alerts.extend(
        _rate_alerts(
            events, now, "modified", RAPID_MODIFY_WINDOW_SECONDS, RAPID_MODIFY_COUNT, "rapid_modifications", "warning"
        )
    )
    alerts.extend(_rate_alerts(events, now, None, BURST_WINDOW_SECONDS, BURST_EVENT_COUNT, "burst_activity", "critical"))

    return alerts


def _rate_alerts(
    events: list[FileEvent],
    now: float,
    event_type: str | None,
    window_seconds: float,
    threshold: int,
    alert_type: str,
    severity: str,
) -> list[ActivityAlert]:
    counts = _count_by_user(events, event_type, now, window_seconds)
    return [
        ActivityAlert(
            timestamp=now,
            alert_type=alert_type,
            username=username,
            detail=f"{count} file(s) {_alert_verb(alert_type)} in the last {int(window_seconds)}s",
            severity=severity,
        )
        for username, count in counts.items()
        if count >= threshold
    ]


def _alert_verb(alert_type: str) -> str:
    return {
        "rapid_deletes": "deleted",
        "rapid_modifications": "modified",
        "burst_activity": "changed",
    }[alert_type]


def _count_by_user(
    events: list[FileEvent], event_type: str | None, now: float, window_seconds: float
) -> dict[str | None, int]:
    counts: dict[str | None, int] = defaultdict(int)
    cutoff = now - window_seconds
    for event in events:
        if event.timestamp < cutoff:
            continue
        if event_type is not None and event.event_type != event_type:
            continue
        counts[event.username] += 1
    return dict(counts)
