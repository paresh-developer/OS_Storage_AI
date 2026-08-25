"""Linux auditd integration: attributes real-time file create/modify/delete
events to the OS user (and process) that actually performed them.

This exists because a plain filesystem watcher (watcher.py, via inotify)
can only ever report "this path changed" -- the kernel's inotify API has no
concept of which user or process did it. The Linux audit subsystem does
track that, but only for paths it's told to watch, and only when running
with the privilege to configure and read it.

Deliberately built against `ausearch`'s *interpreted* output (`-i`) rather
than hand-parsing /var/log/audit/audit.log directly: `-i` already resolves
uid -> username and syscall numbers -> names, both of which are otherwise
architecture-specific translation tables this app would have to maintain
and keep in sync with the kernel itself. The handful of fields this parser
depends on (`nametype`, `name`, `uid`, `comm`, `exe`, `pid`) are part of
the audit record format's stable, documented core; noisier fields (SELinux
context, capability bits, ...) are ignored rather than depended on.

Requires, on the target machine:
1. `auditd` and its userspace tools (`auditctl`, `ausearch`) installed and
   the auditd service running.
2. Root (or CAP_AUDIT_CONTROL / CAP_AUDIT_READ) to install watches and read
   audit records -- this module never silently degrades attribution
   quality; every failure raises AuditUnavailable with the exact command
   to run manually, so the caller can surface that plainly instead of
   pretending to have real attribution it doesn't have.

NOTE: this module's live event-capture path could not be exercised against
a real auditd instance in the environment it was written in (no auditd
installed, no root) -- see docs/METHODOLOGY.md for what was and wasn't
verified. The parser itself is thoroughly unit-tested against realistic,
standards-documented `ausearch -i` sample output.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

_FIELD_RE = re.compile(r'(\w+)=("[^"]*"|\S+)')
_RECORD_RE = re.compile(r"type=(\w+)\s+msg=audit\((\d+)\.(\d+):(\d+)\)\s*:?\s*(.*)")

_NAMETYPE_TO_EVENT_TYPE = {
    "CREATE": "created",
    "DELETE": "deleted",
    "NORMAL": "modified",
}

DEFAULT_KEY = "storage_ai_watch"


class AuditUnavailable(Exception):
    """Raised when auditd/ausearch tooling isn't present, or this process
    lacks permission to use it. Callers should surface this to the user
    rather than silently falling back to a weaker attribution method."""


@dataclass
class AuditFileEvent:
    timestamp: float
    path: str
    event_type: str  # "created" | "modified" | "deleted"
    username: str | None
    pid: int | None
    process_name: str | None


def is_available() -> bool:
    """True only if both CLI tools exist -- does not confirm this process
    actually has permission to use them (that's checked by trying, in
    install_watch/fetch_events, since it's the only reliable way)."""
    return shutil.which("ausearch") is not None and shutil.which("auditctl") is not None


def install_watch(path: str, key: str = DEFAULT_KEY) -> None:
    """Adds an audit watch rule covering writes and attribute changes under
    `path`. Requires root -- raises AuditUnavailable with the exact command
    to run manually if this process can't do it directly."""
    if shutil.which("auditctl") is None:
        raise AuditUnavailable("auditctl not found -- install your distro's 'audit' package.")

    result = subprocess.run(
        ["auditctl", "-w", path, "-p", "wa", "-k", key],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AuditUnavailable(
            f"Could not install an audit watch on {path} ({result.stderr.strip()}). "
            f"Run this once as root: sudo auditctl -w {path} -p wa -k {key}"
        )


def remove_watch(path: str, key: str = DEFAULT_KEY) -> None:
    """Best-effort cleanup -- deliberately does not raise, since this runs
    during shutdown and a failure here shouldn't mask the real reason the
    service is stopping."""
    if shutil.which("auditctl") is None:
        return
    subprocess.run(["auditctl", "-W", path, "-k", key], capture_output=True, text=True)


def fetch_events(key: str = DEFAULT_KEY, start: str = "recent") -> list[AuditFileEvent]:
    """Runs `ausearch -k <key> -i --start <start>` and parses the result.
    `start` accepts anything ausearch understands: "recent", "today", or an
    explicit "MM/DD/YYYY HH:MM:SS"."""
    if shutil.which("ausearch") is None:
        raise AuditUnavailable("ausearch not found -- install your distro's 'audit' package.")

    result = subprocess.run(
        ["ausearch", "-k", key, "-i", "--start", start],
        capture_output=True,
        text=True,
    )
    # ausearch exits 1 when the search simply found nothing -- not an error.
    if result.returncode not in (0, 1):
        raise AuditUnavailable(
            f"ausearch failed ({result.stderr.strip()}). This usually means the process "
            "lacks permission to read audit records -- try running as root."
        )
    return parse_ausearch_output(result.stdout)


def parse_ausearch_output(text: str) -> list[AuditFileEvent]:
    events: list[AuditFileEvent] = []
    for block in text.split("----"):
        block = block.strip()
        if block:
            events.extend(_parse_block(block))
    return events


def _parse_block(block: str) -> list[AuditFileEvent]:
    records: dict[str, list[dict[str, str]]] = {}
    timestamp: float | None = None

    for line in block.splitlines():
        line = line.strip()
        match = _RECORD_RE.match(line)
        if not match:
            continue
        record_type, epoch, millis, _serial, rest = match.groups()
        fields = {k: v.strip('"') for k, v in _FIELD_RE.findall(rest)}
        records.setdefault(record_type, []).append(fields)
        if timestamp is None:
            timestamp = float(f"{epoch}.{millis}")

    if timestamp is None:
        return []

    syscall = records.get("SYSCALL", [{}])[0]
    username = syscall.get("uid")
    pid = int(syscall["pid"]) if syscall.get("pid", "").isdigit() else None
    process_name = syscall.get("comm")

    events: list[AuditFileEvent] = []
    for path_record in records.get("PATH", []):
        event_type = _NAMETYPE_TO_EVENT_TYPE.get(path_record.get("nametype", ""))
        name = path_record.get("name")
        if event_type is None or not name:
            continue
        events.append(
            AuditFileEvent(
                timestamp=timestamp,
                path=name,
                event_type=event_type,
                username=username,
                pid=pid,
                process_name=process_name,
            )
        )
    return events
