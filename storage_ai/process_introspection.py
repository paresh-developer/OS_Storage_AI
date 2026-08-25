"""Discovers a running process's actual storage/config paths from the
kernel's own record of it, via /proc -- Linux only.

This exists to answer a hard question honestly: for an application this
tool has never been told about, how would it find that app's data
directory? A curated lookup table (path_classifier.py) only ever knows
what it's been explicitly taught. This module sidesteps that limit for the
one case where the OS itself already has the answer: if the application is
*currently running*, /proc/<pid>/cmdline often names its config/data path
directly (most daemons accept a --config/-c/--datadir-style flag), and
/proc/<pid>/fd lists every file it actually has open right now -- which is
stronger evidence than any config file, because it's observing what the
process is really doing, not what a setting merely claims it will do.

Neither signal requires knowing anything about the specific application in
advance. Both degrade gracefully: a process not owned by the current user
can't have its /proc entries read without root, which is a normal,
expected permission boundary (same posture as audit_log.py), not an error
to work around.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# Command-line flags that conventionally take a config/data path as their
# value, either as "--flag value" or "--flag=value". Deliberately generic
# (not tied to any specific application) so this works for software this
# module has never heard of.
_PATH_FLAG_RE = re.compile(
    r"^-{1,2}(config|conf|c|datadir|data-dir|data_dir|dbpath|db-path|"
    r"storage-path|storagepath|logdir|log-dir|pidfile)$",
    re.IGNORECASE,
)


@dataclass
class ProcessPathHint:
    path: str
    confidence: str  # "cmdline_flag" | "open_fd"
    detail: str  # e.g. the flag name, or "open file descriptor"


@dataclass
class ProcessStorageInfo:
    pid: int
    process_name: str
    cmdline: list[str] = field(default_factory=list)
    hints: list[ProcessPathHint] = field(default_factory=list)


def find_pids_by_name(name: str) -> list[int]:
    """PIDs whose /proc/<pid>/comm matches `name` exactly (comm is
    truncated to 15 chars by the kernel, matching this project's actual
    process names like "mongod" or "postgres" without truncation issues
    in practice)."""
    matches = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm") as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm == name:
            matches.append(int(entry))
    return matches


def list_running_process_names() -> list[str]:
    """Every distinct process name (/proc/<pid>/comm) currently visible on
    this machine, deduplicated and sorted. The starting point for batch
    discovery across every running application at once (app_suggestions.py),
    as opposed to find_pids_by_name's "one app I already have a name for"."""
    names = set()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm") as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm:
            names.add(comm)
    return sorted(names)


def read_cmdline(pid: int) -> list[str] | None:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return [part for part in raw.decode("utf-8", errors="replace").split("\x00") if part]


def _extract_cmdline_hints(cmdline: list[str]) -> list[ProcessPathHint]:
    hints = []
    for i, arg in enumerate(cmdline):
        if "=" in arg and arg.startswith("-"):
            flag, _, value = arg.partition("=")
            if _PATH_FLAG_RE.match(flag) and value:
                hints.append(ProcessPathHint(path=value, confidence="cmdline_flag", detail=flag))
        elif _PATH_FLAG_RE.match(arg) and i + 1 < len(cmdline):
            value = cmdline[i + 1]
            if not value.startswith("-"):
                hints.append(ProcessPathHint(path=value, confidence="cmdline_flag", detail=arg))
    return hints


def list_open_paths(pid: int) -> list[str]:
    """Real filesystem paths the process currently has open, from
    /proc/<pid>/fd's symlinks. Requires owning the process (or root) --
    returns an empty list rather than raising if that's not the case, same
    as the rest of this module's permission posture."""
    fd_dir = f"/proc/{pid}/fd"
    paths = []
    try:
        entries = os.listdir(fd_dir)
    except OSError:
        return []
    for entry in entries:
        try:
            target = os.readlink(os.path.join(fd_dir, entry))
        except OSError:
            continue
        # Skip pipes, sockets, and anonymous inodes -- only real filesystem
        # paths are useful signal here.
        if target.startswith("/") and not target.startswith(("/proc/", "/dev/", "/sys/")):
            paths.append(target)
    return paths


def _extract_open_fd_hints(pid: int) -> list[ProcessPathHint]:
    return [
        ProcessPathHint(path=path, confidence="open_fd", detail="open file descriptor")
        for path in list_open_paths(pid)
    ]


def discover_storage_paths(pid: int) -> ProcessStorageInfo | None:
    """Combines both signals for one running process. Returns None if the
    process no longer exists (it may have exited between being found and
    being inspected -- not treated as an error)."""
    cmdline = read_cmdline(pid)
    if cmdline is None:
        return None

    try:
        with open(f"/proc/{pid}/comm") as f:
            process_name = f.read().strip()
    except OSError:
        process_name = cmdline[0] if cmdline else "?"

    hints = _extract_cmdline_hints(cmdline) + _extract_open_fd_hints(pid)
    return ProcessStorageInfo(pid=pid, process_name=process_name, cmdline=cmdline, hints=hints)


def discover_storage_paths_by_name(name: str) -> list[ProcessStorageInfo]:
    """Convenience wrapper: find every running process named `name` and
    discover storage-path hints for each."""
    results = []
    for pid in find_pids_by_name(name):
        info = discover_storage_paths(pid)
        if info is not None:
            results.append(info)
    return results
