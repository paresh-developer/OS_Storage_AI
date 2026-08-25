"""Tests the live watcher against real filesystem events (real inotify on
Linux -- this needs no root, unlike audit_log.py). Events arrive
asynchronously on the watchdog observer thread, so each test polls with a
timeout rather than asserting immediately."""

from __future__ import annotations

import errno
import os
import time

import pytest

from storage_ai.watcher import LiveWatcher, LiveWatcherError, iter_watchable_dirs

_POLL_TIMEOUT = 5.0
_POLL_INTERVAL = 0.05


def _wait_until(predicate, timeout=_POLL_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_INTERVAL)
    return False


def test_detects_file_creation(tmp_path):
    events = []
    watcher = LiveWatcher([str(tmp_path)], events.append)
    watcher.start()
    try:
        assert _wait_until(lambda: watcher.is_alive)
        (tmp_path / "new_file.txt").write_text("hello")

        assert _wait_until(lambda: any(e.event_type == "created" for e in events))
        created = next(e for e in events if e.event_type == "created")
        assert created.path == str(tmp_path / "new_file.txt")
        assert created.size == len("hello")
        assert created.attribution_source == "stat"
        assert created.username is not None
    finally:
        watcher.stop()


def test_detects_file_modification(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("v1")

    events = []
    watcher = LiveWatcher([str(tmp_path)], events.append)
    watcher.start()
    try:
        assert _wait_until(lambda: watcher.is_alive)
        target.write_text("v2 -- longer content")

        assert _wait_until(lambda: any(e.event_type == "modified" for e in events))
        modified = next(e for e in events if e.event_type == "modified")
        assert modified.path == str(target)
        assert modified.size == len("v2 -- longer content")
    finally:
        watcher.stop()


def test_detects_file_deletion(tmp_path):
    target = tmp_path / "to_delete.txt"
    target.write_text("bye")

    events = []
    watcher = LiveWatcher([str(tmp_path)], events.append)
    watcher.start()
    try:
        assert _wait_until(lambda: watcher.is_alive)
        os.remove(target)

        assert _wait_until(lambda: any(e.event_type == "deleted" for e in events))
        deleted = next(e for e in events if e.event_type == "deleted")
        assert deleted.path == str(target)
        assert deleted.size is None
        assert deleted.uid is None
        assert deleted.username is None
    finally:
        watcher.stop()


def test_directory_events_are_not_reported_as_file_events(tmp_path):
    events = []
    watcher = LiveWatcher([str(tmp_path)], events.append)
    watcher.start()
    try:
        assert _wait_until(lambda: watcher.is_alive)
        (tmp_path / "a_subdir").mkdir()
        # A brief pause before writing inside the new directory: registering
        # a watch on a directory created *during* monitoring happens
        # reactively (on_created -> schedule a watch for it), which has a
        # real but very narrow (sub-10ms in practice) race window against
        # something writing into it immediately. Real usage essentially
        # never hits this; a bare mkdir()-then-write with no gap at all can.
        time.sleep(0.1)
        (tmp_path / "a_subdir" / "inner.txt").write_text("x")

        assert _wait_until(lambda: any(e.path.endswith("inner.txt") for e in events))
        assert all("a_subdir" != os.path.basename(e.path) for e in events)
    finally:
        watcher.stop()


def test_new_subdirectory_created_during_monitoring_is_recursively_covered(tmp_path):
    """Dedicated regression test for dynamic coverage extension: watching a
    root non-recursively-per-directory (see watcher.py's iter_watchable_dirs)
    must still pick up files created inside a brand-new nested subdirectory
    tree, not just the top-level root's pre-existing contents."""
    events = []
    watcher = LiveWatcher([str(tmp_path)], events.append)
    watcher.start()
    try:
        assert _wait_until(lambda: watcher.is_alive)

        nested = tmp_path / "new_top" / "new_nested"
        nested.mkdir(parents=True)
        time.sleep(0.1)
        (nested / "deep.txt").write_text("hello")

        assert _wait_until(lambda: any(e.path.endswith("deep.txt") for e in events))
    finally:
        watcher.stop()


def test_stop_actually_stops_the_observer_thread(tmp_path):
    watcher = LiveWatcher([str(tmp_path)], lambda e: None)
    watcher.start()
    assert _wait_until(lambda: watcher.is_alive)

    watcher.stop()
    assert watcher.is_alive is False


def test_start_on_nonexistent_path_raises_live_watcher_error():
    watcher = LiveWatcher(["/definitely/does/not/exist/xyz"], lambda e: None)

    with pytest.raises(LiveWatcherError):
        watcher.start()


def test_stop_after_a_failed_start_does_not_raise(tmp_path):
    """Regression test: watchdog validates the watch path synchronously
    inside start() -- when that fails, the observer's own thread is never
    actually started, so stop() must not try to join it (previously raised
    RuntimeError: cannot join thread before it is started)."""
    watcher = LiveWatcher(["/definitely/does/not/exist/xyz"], lambda e: None)

    with pytest.raises(LiveWatcherError):
        watcher.start()

    watcher.stop()  # must not raise
    assert watcher.is_alive is False


def test_is_alive_is_false_after_a_failed_start():
    watcher = LiveWatcher(["/definitely/does/not/exist/xyz"], lambda e: None)

    with pytest.raises(LiveWatcherError):
        watcher.start()

    assert watcher.is_alive is False


def test_enospc_gets_a_friendly_inotify_limit_message(tmp_path, monkeypatch):
    watcher = LiveWatcher([str(tmp_path)], lambda e: None)

    def _raise_enospc(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(watcher._observer, "start", _raise_enospc)

    with pytest.raises(LiveWatcherError, match="inotify watch limit"):
        watcher.start()

    watcher.stop()  # still must not raise


def test_iter_watchable_dirs_yields_root_and_prunes_excluded(tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "nested").mkdir()

    found = set(iter_watchable_dirs(str(tmp_path), {"node_modules"}))

    assert str(tmp_path) in found
    assert str(tmp_path / "keep") in found
    assert str(tmp_path / "node_modules") not in found
    assert str(tmp_path / "node_modules" / "nested") not in found


def test_events_inside_excluded_directories_are_never_captured(tmp_path):
    (tmp_path / "node_modules").mkdir()

    events = []
    watcher = LiveWatcher([str(tmp_path)], events.append, excludes={"node_modules"})
    watcher.start()
    try:
        assert _wait_until(lambda: watcher.is_alive)
        (tmp_path / "node_modules" / "dep.js").write_text("noise")
        (tmp_path / "real_file.txt").write_text("signal")  # confirms the watcher is otherwise working

        assert _wait_until(lambda: any(e.path.endswith("real_file.txt") for e in events))
        assert not any("node_modules" in e.path for e in events)
    finally:
        watcher.stop()


def test_permission_denied_subdirectory_does_not_prevent_watching_the_rest(tmp_path):
    """Regression test for watching a broad root (e.g. as a non-root user):
    a single unreadable subdirectory anywhere in the tree used to abort the
    entire watch setup (recursive=True on the raw root fails outright the
    moment it reaches one such directory) -- now it's just skipped, and
    everything else is still watched."""
    restricted = tmp_path / "no_access"
    restricted.mkdir()
    restricted.chmod(0o000)

    events = []
    try:
        watcher = LiveWatcher([str(tmp_path)], events.append)
        watcher.start()
        try:
            assert _wait_until(lambda: watcher.is_alive)
            (tmp_path / "visible.txt").write_text("hello")

            assert _wait_until(lambda: any(e.path.endswith("visible.txt") for e in events))
        finally:
            watcher.stop()
    finally:
        restricted.chmod(0o755)  # restore so pytest can clean up tmp_path
