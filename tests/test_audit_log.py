"""Tests for the ausearch -i output parser, against realistic sample text
matching the documented audit record format (man ausearch, man audit.log).
This machine has no auditd installed, so these tests validate the parsing
logic against known-correct sample data rather than a live audit stream --
see docs/METHODOLOGY.md for what that means for verification coverage."""

from __future__ import annotations

from storage_ai.audit_log import parse_ausearch_output

_DELETE_SAMPLE = """
----
time->Tue Aug 20 10:15:23 2026
type=PROCTITLE msg=audit(1755683723.456:789) : proctitle=rm /home/alice/bigfile.mp4
type=PATH msg=audit(1755683723.456:789) : item=0 name=/home/alice/bigfile.mp4 inode=131099 dev=08:01 mode=file,644 ouid=alice ogid=alice rdev=00:00 nametype=DELETE
type=CWD msg=audit(1755683723.456:789) : cwd=/home/alice
type=SYSCALL msg=audit(1755683723.456:789) : arch=x86_64 syscall=unlink success=yes exit=0 items=1 ppid=999 pid=1234 auid=alice uid=alice gid=alice euid=alice suid=alice fsuid=alice egid=alice sgid=alice fsgid=alice tty=pts0 ses=3 comm=rm exe=/usr/bin/rm key=storage_ai_watch
"""

_CREATE_SAMPLE = """
----
time->Tue Aug 20 10:16:00 2026
type=PATH msg=audit(1755683760.100:790) : item=1 name=/home/bob/report.docx inode=131200 dev=08:01 mode=file,644 ouid=bob ogid=bob rdev=00:00 nametype=CREATE
type=PATH msg=audit(1755683760.100:790) : item=0 name=/home/bob inode=131050 dev=08:01 mode=dir,755 ouid=bob ogid=bob rdev=00:00 nametype=PARENT
type=CWD msg=audit(1755683760.100:790) : cwd=/home/bob
type=SYSCALL msg=audit(1755683760.100:790) : arch=x86_64 syscall=openat success=yes exit=3 items=2 ppid=500 pid=5678 auid=bob uid=bob gid=bob euid=bob comm=vim exe=/usr/bin/vim key=storage_ai_watch
"""

_MODIFY_SAMPLE = """
----
time->Tue Aug 20 10:17:00 2026
type=PATH msg=audit(1755683820.200:791) : item=0 name=/srv/shared/notes.txt inode=131300 dev=08:01 mode=file,644 ouid=carol ogid=carol rdev=00:00 nametype=NORMAL
type=CWD msg=audit(1755683820.200:791) : cwd=/srv/shared
type=SYSCALL msg=audit(1755683820.200:791) : arch=x86_64 syscall=openat success=yes exit=3 items=1 ppid=1 pid=42 auid=carol uid=carol gid=carol comm=nano exe=/usr/bin/nano key=storage_ai_watch
"""

_MULTI_EVENT_SAMPLE = _DELETE_SAMPLE + _CREATE_SAMPLE


def test_parses_delete_event_with_username_and_process():
    [event] = parse_ausearch_output(_DELETE_SAMPLE)

    assert event.event_type == "deleted"
    assert event.path == "/home/alice/bigfile.mp4"
    assert event.username == "alice"
    assert event.pid == 1234
    assert event.process_name == "rm"
    assert event.timestamp == 1755683723.456


def test_parses_create_event_and_skips_parent_directory_record():
    [event] = parse_ausearch_output(_CREATE_SAMPLE)

    assert event.event_type == "created"
    assert event.path == "/home/bob/report.docx"
    assert event.username == "bob"
    assert event.process_name == "vim"


def test_parses_modify_event_from_normal_nametype():
    [event] = parse_ausearch_output(_MODIFY_SAMPLE)

    assert event.event_type == "modified"
    assert event.path == "/srv/shared/notes.txt"
    assert event.username == "carol"


def test_parses_multiple_events_in_one_ausearch_dump():
    events = parse_ausearch_output(_MULTI_EVENT_SAMPLE)

    assert len(events) == 2
    assert {e.username for e in events} == {"alice", "bob"}
    assert {e.event_type for e in events} == {"deleted", "created"}


def test_empty_output_returns_no_events():
    assert parse_ausearch_output("") == []
    assert parse_ausearch_output("<no matches>") == []


def test_malformed_block_is_skipped_without_raising():
    garbage = "----\nthis is not a valid audit record\n----\n" + _DELETE_SAMPLE
    events = parse_ausearch_output(garbage)

    assert len(events) == 1
    assert events[0].username == "alice"


def test_block_without_syscall_record_still_extracts_path_events():
    # PATH-only block (no SYSCALL line) -- username/pid/process gracefully
    # become None rather than raising.
    partial = """
----
type=PATH msg=audit(1755683900.000:800) : item=0 name=/tmp/x.txt nametype=DELETE
"""
    [event] = parse_ausearch_output(partial)

    assert event.path == "/tmp/x.txt"
    assert event.event_type == "deleted"
    assert event.username is None
    assert event.pid is None
