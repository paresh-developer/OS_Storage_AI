"""Combines every storage-path discovery signal into one ranked result, in
order of reliability -- a later, weaker tier only runs when earlier,
stronger tiers found nothing, since a cheaper and more certain answer is
always preferable to a more expensive and less certain one:

1. **Process introspection** (process_introspection.py) -- observes what a
   currently-running process is actually doing (its command-line flags,
   its open file descriptors). Strongest signal: it's reality, not a claim.
2. **Structured config discovery** (config_discovery.py) -- parses a
   config file's declared setting (JSON/YAML/TOML/INI). Works even if the
   service isn't running, but a config can be stale or overridden by a
   flag the process was actually started with.
3. **The optional local LLM extractor** (llm_config_extractor.py) -- tried
   only when a config file exists but didn't parse as any supported
   structured format (an exotic/freeform config), and only if the optional
   `transformers`/`torch` dependency is installed. Silently skipped
   otherwise -- this app never requires it.

The curated known-service table (path_classifier.py) is deliberately not
a tier here: its job is classifying a path you already have into a
category, the opposite direction from "given an app name, find its path."
It's used elsewhere to enrich a scan's category breakdown, not to
discover paths in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from storage_ai import config_discovery, process_introspection

_PROCESS_CONFIDENCE = {"cmdline_flag": 0.95, "open_fd": 0.9}

# The LLM tier's own confidence numbers (0.4-0.6, see llm_config_extractor.py)
# aren't directly comparable to the deterministic tiers' scores -- this
# discount keeps LLM-sourced findings visibly, honestly lower-ranked even
# when the model itself reports a moderately high score.
_LLM_CONFIDENCE_DISCOUNT = 0.7


@dataclass
class StoragePathFinding:
    path: str
    confidence: float
    source: str  # "process_cmdline_flag" | "process_open_fd" | "config_file" | "llm_extraction"
    detail: str


def discover_app_storage_paths(app_name: str, try_llm_fallback: bool = True) -> list[StoragePathFinding]:
    findings = _from_running_processes(app_name)
    if findings:
        return findings

    findings = _from_config_files(app_name)
    if findings:
        return findings

    if try_llm_fallback:
        findings = _from_llm_fallback(app_name)

    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings


def _from_running_processes(app_name: str) -> list[StoragePathFinding]:
    findings = []
    for info in process_introspection.discover_storage_paths_by_name(app_name):
        for hint in info.hints:
            findings.append(
                StoragePathFinding(
                    path=hint.path,
                    confidence=_PROCESS_CONFIDENCE[hint.confidence],
                    source=f"process_{hint.confidence}",
                    detail=f"pid {info.pid} ({info.process_name}): {hint.detail}",
                )
            )
    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings


def _from_config_files(app_name: str) -> list[StoragePathFinding]:
    findings = []
    for discovered in config_discovery.discover_config(app_name):
        for candidate in discovered.candidates:
            findings.append(
                StoragePathFinding(
                    path=candidate.value,
                    confidence=candidate.confidence,
                    source="config_file",
                    detail=f"{discovered.config_path} -> {candidate.key_path}",
                )
            )
    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings


def _from_llm_fallback(app_name: str) -> list[StoragePathFinding]:
    """Only reached when structured parsing found nothing at all for this
    app -- either there's no candidate config file, or one exists but
    didn't parse as JSON/YAML/TOML/INI (config_discovery.parse_config_file
    returned None), which is exactly the case an extractive read of the
    raw text might still help with. A config that parsed fine but simply
    had no path-shaped setting in it does NOT reach this tier -- that's a
    confirmed structured answer of "nothing here," not a parsing gap."""
    from storage_ai import llm_config_extractor

    if not llm_config_extractor.is_available():
        return []

    findings = []
    for config_path in config_discovery.find_candidate_config_files(app_name):
        if config_discovery.parse_config_file(config_path) is not None:
            continue
        try:
            text = Path(config_path).read_text(errors="replace")
        except OSError:
            continue

        try:
            result = llm_config_extractor.extract_storage_path(text)
        except llm_config_extractor.LLMUnavailable:
            break
        if result is not None:
            findings.append(
                StoragePathFinding(
                    path=result.path,
                    confidence=result.confidence * _LLM_CONFIDENCE_DISCOUNT,
                    source="llm_extraction",
                    detail=f"{config_path} (question: {result.question!r})",
                )
            )

    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings
