"""Standalone, independently-runnable background service: watches one or
more directory trees for live file activity and persists everything to the
shared SQLite database, so it keeps collecting whether or not the desktop
GUI is even open. This is the piece that makes "run without stopping" on a
server actually true -- the GUI is a viewer over what this collects, not a
requirement for collecting it.

Usage:
    python -m storage_ai.watcher_service /srv/shared
    python -m storage_ai.watcher_service --enable-audit /srv/shared    # Linux, needs root

Install as a systemd service to survive reboots on a headless server --
see docs/METHODOLOGY.md for a sample unit file and the auditd setup steps
--enable-audit depends on.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from storage_ai import audit_log, database
from storage_ai.config import DB_PATH
from storage_ai.models import file_event_from_row
from storage_ai.trend_detector import detect_alerts
from storage_ai.watcher import LiveWatcher, LiveWatcherError

_AUDIT_POLL_INTERVAL_SECONDS = 5
_TREND_CHECK_INTERVAL_SECONDS = 30
_TREND_WINDOW_SECONDS = 300  # look back 5 minutes for rate-based detection
_ALERT_COOLDOWN_SECONDS = 300  # don't re-fire the identical alert more than once per window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Storage AI live-activity watcher service")
    parser.add_argument("paths", nargs="+", help="Directories to watch, recursively")
    parser.add_argument(
        "--enable-audit",
        action="store_true",
        help="Also install auditd watches for real per-operation user attribution (Linux, requires root)",
    )
    args = parser.parse_args(argv)

    if args.enable_audit and not audit_log.is_available():
        print(
            "--enable-audit requested but auditd/ausearch tooling isn't available on this machine.",
            file=sys.stderr,
        )
        return 1

    if args.enable_audit:
        for path in args.paths:
            try:
                audit_log.install_watch(path)
            except audit_log.AuditUnavailable as exc:
                print(str(exc), file=sys.stderr)
                return 1
        print(f"auditd watch installed for: {', '.join(args.paths)}")

    try:
        _run(args.paths, enable_audit=args.enable_audit)
    except LiveWatcherError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if args.enable_audit:
            for path in args.paths:
                audit_log.remove_watch(path)

    return 0


def _run(paths: list[str], enable_audit: bool, db_path: str | Path = DB_PATH) -> None:
    stop_requested = {"value": False}

    def _handle_signal(signum, frame):
        stop_requested["value"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    watcher = LiveWatcher(paths, lambda event: database.record_file_event(event, db_path=db_path))
    watcher.start()
    print(f"Watching: {', '.join(paths)} (Ctrl+C to stop)")

    last_audit_poll = 0.0
    last_trend_check = 0.0
    recent_alert_keys: dict[tuple, float] = {}

    try:
        while not stop_requested["value"]:
            time.sleep(1)
            now = time.time()

            if enable_audit and now - last_audit_poll >= _AUDIT_POLL_INTERVAL_SECONDS:
                _poll_audit_events(db_path=db_path)
                last_audit_poll = now

            if now - last_trend_check >= _TREND_CHECK_INTERVAL_SECONDS:
                _check_trends(now, recent_alert_keys, db_path=db_path)
                last_trend_check = now
    finally:
        watcher.stop()


def _poll_audit_events(db_path: str | Path = DB_PATH) -> None:
    try:
        for audit_event in audit_log.fetch_events():
            database.upgrade_event_attribution(audit_event, db_path=db_path)
    except audit_log.AuditUnavailable as exc:
        print(f"audit polling failed: {exc}", file=sys.stderr)


def _check_trends(now: float, recent_alert_keys: dict[tuple, float], db_path: str | Path = DB_PATH) -> None:
    rows = database.get_recent_file_events(since=now - _TREND_WINDOW_SECONDS, db_path=db_path)
    events = [file_event_from_row(r) for r in rows]

    for alert in detect_alerts(events, now=now):
        key = (alert.alert_type, alert.username)
        last_fired = recent_alert_keys.get(key)
        if last_fired is not None and now - last_fired < _ALERT_COOLDOWN_SECONDS:
            continue
        database.record_alert(alert, db_path=db_path)
        recent_alert_keys[key] = now
        print(f"[{alert.severity}] {alert.alert_type} -- {alert.username}: {alert.detail}")


if __name__ == "__main__":
    sys.exit(main())
