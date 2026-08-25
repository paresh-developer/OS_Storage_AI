"""Tests process_introspection.py against a real running process -- not a
mock. A small Python subprocess stands in for "some daemon this tool has
never heard of," started with a --datadir-style flag and an open file
inside that directory, so both discovery signals (cmdline flags, open fds)
get exercised against ground truth."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from storage_ai.process_introspection import (
    discover_storage_paths,
    discover_storage_paths_by_name,
    find_pids_by_name,
    list_open_paths,
    read_cmdline,
)

_STUB_SCRIPT = (
    "import sys, time\n"
    "f = open(sys.argv[2] + '/data.db', 'wb')\n"
    "f.write(b'x')\n"
    "f.flush()\n"
    "time.sleep(30)\n"
)


@pytest.fixture
def fake_daemon(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", _STUB_SCRIPT, "--datadir", str(tmp_path)])
    try:
        deadline = time.time() + 5
        while not (tmp_path / "data.db").exists() and time.time() < deadline:
            time.sleep(0.05)
        yield proc, tmp_path
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_read_cmdline_for_a_real_process(fake_daemon):
    proc, tmp_path = fake_daemon

    cmdline = read_cmdline(proc.pid)

    assert cmdline is not None
    assert "--datadir" in cmdline
    assert str(tmp_path) in cmdline


def test_read_cmdline_returns_none_for_a_dead_process():
    # A PID that (almost certainly) doesn't correspond to a live process.
    assert read_cmdline(999999) is None


def test_discover_storage_paths_finds_cmdline_flag_hint(fake_daemon):
    proc, tmp_path = fake_daemon

    info = discover_storage_paths(proc.pid)

    assert info is not None
    flag_hints = [h for h in info.hints if h.confidence == "cmdline_flag"]
    assert any(h.path == str(tmp_path) and h.detail == "--datadir" for h in flag_hints)


def test_discover_storage_paths_finds_open_fd_hint(fake_daemon):
    proc, tmp_path = fake_daemon

    info = discover_storage_paths(proc.pid)

    fd_hints = [h for h in info.hints if h.confidence == "open_fd"]
    assert any(str(tmp_path) in h.path for h in fd_hints)


def test_list_open_paths_excludes_pipes_and_special_files(fake_daemon):
    proc, tmp_path = fake_daemon

    paths = list_open_paths(proc.pid)

    assert all(not p.startswith(("/proc/", "/dev/", "/sys/")) for p in paths)


def test_discover_storage_paths_returns_none_for_nonexistent_pid():
    assert discover_storage_paths(999999) is None


def test_find_pids_by_name_and_discover_by_name(fake_daemon):
    proc, tmp_path = fake_daemon

    # Our own comm name is whatever `sys.executable` resolves to at the OS
    # level (commonly "python3" or "python3.13") -- discover it generically
    # via read_cmdline on all matching PIDs rather than hardcoding a name.
    with open(f"/proc/{proc.pid}/comm") as f:
        real_comm = f.read().strip()

    pids = find_pids_by_name(real_comm)
    assert proc.pid in pids

    infos = discover_storage_paths_by_name(real_comm)
    matching = [i for i in infos if i.pid == proc.pid]
    assert matching
    assert any(h.path == str(tmp_path) for h in matching[0].hints)
