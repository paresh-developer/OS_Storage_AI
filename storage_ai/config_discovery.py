"""Discovers and parses an application's config file to find a likely
storage/data-path setting, without needing to know the app's exact config
location or key-naming convention in advance.

Complements process_introspection.py (which only works for a currently
running process) for the case where you want the *declared* configuration
even if the service isn't running right now, or want a second, independent
signal to cross-check against.

This is inherently a lower-confidence signal than process_introspection.py's
open-fd evidence: it reports what a config *says*, not what the process is
*actually doing* (and a config can be stale, overridden by a CLI flag, or
just wrong). Confidence is scored accordingly -- callers should prefer a
process_introspection hit when one exists, and treat this as corroboration
or a fallback, not a replacement.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

# Deliberately generic key-name patterns, not tied to any specific
# application's naming convention (MongoDB's "storage.dbPath", Postgres's
# "data_directory", a hypothetical app's "storagePath" all match).
_KEY_NAME_RE = re.compile(r"(path|dir|directory|storage|dbpath|datadir)", re.IGNORECASE)

_CANDIDATE_TEMPLATES = [
    "{etc}/{app}.conf",
    "{etc}/{app}.yaml",
    "{etc}/{app}.yml",
    "{etc}/{app}.json",
    "{etc}/{app}.toml",
    "{etc}/{app}/{app}.conf",
    "{etc}/{app}/{app}.yaml",
    "{etc}/{app}/{app}.yml",
    "{etc}/{app}/config.yaml",
    "{etc}/{app}/config.yml",
    "{etc}/{app}/config.json",
    "{etc}/{app}/config.toml",
]


@dataclass
class PathCandidate:
    key_path: str  # dotted path within the config, e.g. "storage.dbPath"
    value: str
    exists_on_disk: bool
    confidence: float  # 0-1, always below process_introspection's open_fd tier


@dataclass
class DiscoveredConfig:
    config_path: str
    format: str
    candidates: list[PathCandidate]


def find_candidate_config_files(app_name: str, home: str | None = None, etc_root: str = "/etc") -> list[str]:
    home = home if home is not None else os.path.expanduser("~")
    templates = [t.format(etc=etc_root, app=app_name) for t in _CANDIDATE_TEMPLATES] + [
        f"{home}/.config/{app_name}/config.yaml",
        f"{home}/.config/{app_name}/config.yml",
        f"{home}/.config/{app_name}/config.json",
        f"{home}/.config/{app_name}/{app_name}.conf",
    ]
    return [path for path in templates if os.path.isfile(path)]


def _unquote(value: str) -> str:
    """postgresql.conf-style files quote string values ("data_directory =
    '/var/lib/postgresql/14/main'"); strip that so the path-shape check
    below actually recognizes them."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def parse_config_file(path: str) -> tuple[dict, str] | None:
    """Returns (parsed_dict, format_name), or None if the file can't be
    read or doesn't match any supported format."""
    suffix = Path(path).suffix.lower()
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return None

    try:
        if suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text)
            return (data if isinstance(data, dict) else {}), "yaml"
        if suffix == ".json":
            return json.loads(text), "json"
        if suffix == ".toml":
            return tomllib.loads(text), "toml"
        if suffix in (".conf", ".ini", ".cfg"):
            parser = configparser.ConfigParser(strict=False, interpolation=None)
            parser.read_string(_ensure_section_header(text))
            return {section: dict(parser.items(section)) for section in parser.sections()}, "ini"
    except Exception:
        return None
    return None


def _ensure_section_header(text: str) -> str:
    """Plenty of real daemon .conf files (postgresql.conf among them) are
    flat `key = value` lines with no [section] header at all, which
    configparser rejects outright -- wrap them in a synthetic section
    rather than failing to parse a file that's perfectly readable, just
    not INI-with-sections. Deliberately not named "DEFAULT": configparser
    treats that name specially and silently excludes it from sections(),
    which would make its keys invisible to the walk below."""
    if not text.lstrip().startswith("["):
        return "[ROOT]\n" + text
    return text


def _walk(data, prefix: str = ""):
    if isinstance(data, dict):
        for key, value in data.items():
            new_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk(value, new_prefix)
    elif isinstance(data, str):
        yield prefix, _unquote(data)


def looks_like_absolute_path(value: str) -> bool:
    if value.startswith("/"):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in "\\/"  # e.g. "C:\data"


def find_storage_path_candidates(config: dict) -> list[PathCandidate]:
    candidates = []
    for key_path, value in _walk(config):
        if not _KEY_NAME_RE.search(key_path):
            continue
        if not looks_like_absolute_path(value):
            continue
        exists = os.path.exists(value)
        candidates.append(
            PathCandidate(
                key_path=key_path,
                value=value,
                exists_on_disk=exists,
                confidence=0.7 if exists else 0.4,
            )
        )
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


def discover_config(app_name: str, home: str | None = None, etc_root: str = "/etc") -> list[DiscoveredConfig]:
    """Finds every candidate config file for `app_name` that parses
    successfully and yields at least one path-shaped, path-named setting."""
    results = []
    for config_path in find_candidate_config_files(app_name, home=home, etc_root=etc_root):
        parsed = parse_config_file(config_path)
        if parsed is None:
            continue
        data, fmt = parsed
        candidates = find_storage_path_candidates(data)
        if candidates:
            results.append(DiscoveredConfig(config_path=config_path, format=fmt, candidates=candidates))
    return results
