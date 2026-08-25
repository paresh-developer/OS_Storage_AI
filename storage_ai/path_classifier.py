"""Classifies scanned paths into broad, cross-platform categories, and
flags which ones must never be offered up for deletion or archiving.

This is deliberately NOT a per-application config parser: PostgreSQL's
data_directory and MongoDB's storage.dbPath are user-configurable, so a
lookup table of "default" install paths is only ever a hint, not a source
of truth. Rather than pretend otherwise, this classifies by well-known path
*patterns*, falling back to a generic category when nothing matches, and
only attaches a specific service name when a path happens to sit at one of
that service's common default locations.

The categories exist for two purposes:
1. Storage/growth visibility broken down by kind of data (dashboard).
2. Safety: paths categorized "system" or "application_data" are excluded
   from the unused-file, duplicate, and clustering analyses entirely (see
   pipeline.py) -- a live database's data files can look "unused" under
   naive access-time heuristics while the database is very much in use, so
   the staleness heuristics that are fine for a Downloads folder are not
   safe to apply to a running service's own files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

CATEGORY_SYSTEM = "system"
CATEGORY_LOG = "log"
CATEGORY_CACHE = "cache"
CATEGORY_APPLICATION_DATA = "application_data"
CATEGORY_USER_DATA = "user_data"
CATEGORY_TRASH = "trash"
CATEGORY_OTHER = "other"

_PROTECTED_CATEGORIES = {CATEGORY_SYSTEM, CATEGORY_APPLICATION_DATA}

_LOG_DIR_NAMES = {"log", "logs"}
# "tmp"/"temp" are deliberately excluded from this name-anywhere set: unlike
# a folder explicitly named "cache", a folder named "tmp" is common enough
# as an ordinary user- or project-chosen name (a personal scratch folder, a
# build directory) that matching it anywhere in the tree is too aggressive.
# The *real* top-level temp directory is still classified via the precise
# absolute-prefix rules below.
_CACHE_DIR_NAMES = {"cache", "caches"}
_TRASH_DIR_NAMES = {"trash", "$recycle.bin", "recycle.bin"}


@dataclass
class PathClassification:
    category: str
    known_service: str | None = None

    @property
    def protected(self) -> bool:
        return self.category in _PROTECTED_CATEGORIES


def _linux_prefix_rules(home: str) -> list[tuple[str, str, str | None]]:
    return [
        ("/boot", CATEGORY_SYSTEM, None),
        ("/usr", CATEGORY_SYSTEM, None),
        ("/lib64", CATEGORY_SYSTEM, None),
        ("/lib", CATEGORY_SYSTEM, None),
        ("/sbin", CATEGORY_SYSTEM, None),
        ("/bin", CATEGORY_SYSTEM, None),
        ("/etc", CATEGORY_SYSTEM, None),
        ("/var/log", CATEGORY_LOG, None),
        ("/var/cache", CATEGORY_CACHE, None),
        ("/tmp", CATEGORY_CACHE, None),
        ("/var/lib/postgresql", CATEGORY_APPLICATION_DATA, "PostgreSQL"),
        ("/var/lib/mysql", CATEGORY_APPLICATION_DATA, "MySQL"),
        ("/var/lib/mariadb", CATEGORY_APPLICATION_DATA, "MariaDB"),
        ("/var/lib/mongodb", CATEGORY_APPLICATION_DATA, "MongoDB"),
        ("/var/lib/mongo", CATEGORY_APPLICATION_DATA, "MongoDB"),
        ("/var/lib/redis", CATEGORY_APPLICATION_DATA, "Redis"),
        ("/var/lib/docker", CATEGORY_APPLICATION_DATA, "Docker"),
        ("/var/lib/elasticsearch", CATEGORY_APPLICATION_DATA, "Elasticsearch"),
        ("/var/lib/grafana", CATEGORY_APPLICATION_DATA, "Grafana"),
        ("/var/lib/prometheus", CATEGORY_APPLICATION_DATA, "Prometheus"),
        ("/var/lib/rabbitmq", CATEGORY_APPLICATION_DATA, "RabbitMQ"),
        ("/var/lib/influxdb", CATEGORY_APPLICATION_DATA, "InfluxDB"),
        ("/var/lib/clickhouse", CATEGORY_APPLICATION_DATA, "ClickHouse"),
        (f"{home}/.cache", CATEGORY_CACHE, None),
        (f"{home}/.local/share/Trash", CATEGORY_TRASH, None),
    ]


def _windows_prefix_rules(programdata: str, program_files: str) -> list[tuple[str, str, str | None]]:
    return [
        (r"C:\Windows", CATEGORY_SYSTEM, None),
        (r"C:\$Recycle.Bin", CATEGORY_TRASH, None),
        (f"{program_files}\\PostgreSQL", CATEGORY_APPLICATION_DATA, "PostgreSQL"),
        (f"{program_files}\\MongoDB", CATEGORY_APPLICATION_DATA, "MongoDB"),
        (f"{program_files}\\Redis", CATEGORY_APPLICATION_DATA, "Redis"),
        (f"{program_files}\\Docker", CATEGORY_APPLICATION_DATA, "Docker"),
        (f"{programdata}\\MySQL", CATEGORY_APPLICATION_DATA, "MySQL"),
        (f"{programdata}\\MongoDB", CATEGORY_APPLICATION_DATA, "MongoDB"),
    ]


def classify_path(
    path: str,
    *,
    is_windows: bool | None = None,
    home: str | None = None,
) -> PathClassification:
    """`is_windows` and `home` are override hooks for testing both
    platforms' rules from a single OS -- production callers should omit
    both and let this read the real platform and home directory."""
    is_windows = (os.name == "nt") if is_windows is None else is_windows
    home = home if home is not None else os.path.expanduser("~")

    text = str(path)
    pure_path = PureWindowsPath(text) if is_windows else PurePosixPath(text)
    sep = "\\" if is_windows else "/"

    if is_windows:
        programdata = os.environ.get("ProgramData", r"C:\ProgramData")
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        rules = _windows_prefix_rules(programdata, program_files)
        text_for_match = text.lower()
        home_for_match = home.lower()
    else:
        rules = _linux_prefix_rules(home)
        text_for_match = text
        home_for_match = home

    for prefix, category, service in rules:
        needle = prefix.lower() if is_windows else prefix
        if text_for_match == needle or text_for_match.startswith(needle + sep):
            return PathClassification(category=category, known_service=service)

    if pure_path.suffix.lower() == ".log":
        return PathClassification(category=CATEGORY_LOG)

    parts_lower = {part.lower() for part in pure_path.parts}
    if parts_lower & _TRASH_DIR_NAMES:
        return PathClassification(category=CATEGORY_TRASH)
    if parts_lower & _LOG_DIR_NAMES:
        return PathClassification(category=CATEGORY_LOG)
    if parts_lower & _CACHE_DIR_NAMES:
        return PathClassification(category=CATEGORY_CACHE)

    if text_for_match == home_for_match or text_for_match.startswith(home_for_match + sep):
        return PathClassification(category=CATEGORY_USER_DATA)

    return PathClassification(category=CATEGORY_OTHER)
