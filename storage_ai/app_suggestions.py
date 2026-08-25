"""Batch application storage-path discovery across every process currently
running on this machine, each finding enriched with the same
category/service classification and advisory text the folder-scan
pipeline uses for its "category advisory" recommendations.

Deliberately a separate orchestrator from pipeline.py's run_analysis: that
one walks a folder tree the user picks; this one walks the OS's running
process table. Different input, different cost profile (one process-list
read plus a handful of small config-file checks per app, vs. hashing an
entire directory tree), so this stays its own independently
runnable/cancellable operation rather than being forced into the same
pipeline.

Reuses app_discovery.py's tiered discovery (process introspection ->
config parsing -> optional local LLM) for each candidate app name -- see
docs/METHODOLOGY.md Section 8. The new logic here is "which app names to
even ask about" (every distinct running process), "is a discovered path
actually worth telling the user about" (does it classify into a
category/service with real advisory text, per category_advisor.py), and
"how much disk is it actually using" (a real filesystem walk of the
discovered path, only for findings that already passed the advice
filter, surfaced as a plain size threshold -- see LARGE_SIZE_BYTES /
CRITICAL_SIZE_BYTES below -- so a 1 TB MongoDB data directory doesn't
just get generic advice, it gets flagged).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from storage_ai import app_discovery, category_advisor, path_classifier, process_introspection
from storage_ai.exceptions import ScanCancelled
from storage_ai.models import ScanProgress

# Universal, near-certain-to-be-noise process names -- shells, the
# interpreter running this app itself, kernel/init helpers. Skipping them
# is purely a speed/noise optimization: app_discovery would just find
# nothing actionable for them anyway (no config file, no matching
# category), so this changes performance, not correctness.
_SKIP_NAMES = {
    "bash", "sh", "zsh", "dash", "fish", "ksh",
    "python3", "python", "systemd", "kthreadd", "init",
    "dbus-daemon", "kworker", "sudo", "env",
}

# Plain, explainable size thresholds for the discovered path's own on-disk
# usage -- same style as trend_detector.py's LARGE_FILE_BYTES: a fixed,
# documented number a user can be told "why did this fire" in exactly
# these terms, not a fuzzy heuristic.
SEVERITY_NORMAL = "normal"
SEVERITY_LARGE = "large"
SEVERITY_CRITICAL = "critical"

LARGE_SIZE_BYTES = 5 * 1024**3  # 5 GB -- worth a closer look
CRITICAL_SIZE_BYTES = 50 * 1024**3  # 50 GB -- worth acting on soon


@dataclass
class AppSuggestion:
    app_name: str
    path: str
    confidence: float
    source: str
    detail: str
    category: str
    known_service: str | None
    advice: str
    size_bytes: int
    severity: str  # SEVERITY_NORMAL | SEVERITY_LARGE | SEVERITY_CRITICAL


def path_size_bytes(path: str) -> int:
    """Real on-disk usage of a discovered path -- a single file's own
    size, or a directory walked and summed. Symlinks aren't followed and
    permission errors are skipped (same posture as scanner.py) rather
    than raising, since a path this module didn't create can legitimately
    contain entries the current user can't read."""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        if not os.path.isdir(path):
            return 0
    except OSError:
        return 0

    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _exc: None):
        for name in files:
            full_path = os.path.join(root, name)
            try:
                if not os.path.islink(full_path):
                    total += os.path.getsize(full_path)
            except OSError:
                continue
    return total


def severity_for_size(size_bytes: int) -> str:
    if size_bytes >= CRITICAL_SIZE_BYTES:
        return SEVERITY_CRITICAL
    if size_bytes >= LARGE_SIZE_BYTES:
        return SEVERITY_LARGE
    return SEVERITY_NORMAL


def discover_running_app_suggestions(
    on_progress: Callable[[ScanProgress], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    try_llm_fallback: bool = True,
) -> list[AppSuggestion]:
    """Checks every distinct running process name and returns one
    AppSuggestion per app whose discovered storage path classifies into a
    category/service with real advisory text -- matching
    category_advisor.py's own "no advice, don't surface it" rule, so this
    stays a list of actionable suggestions rather than a firehose of every
    running process.

    Raises ScanCancelled (rather than returning a partial list) once
    `cancel_check` reports True, mirroring pipeline.run_analysis's own
    cancellation contract so the GUI layer can handle both the same way.
    """
    names = [n for n in process_introspection.list_running_process_names() if n not in _SKIP_NAMES]
    total = len(names)

    suggestions = []
    for i, name in enumerate(names):
        if cancel_check is not None and cancel_check():
            raise ScanCancelled()
        if on_progress is not None:
            on_progress(ScanProgress(message=f"Checking {name}... ({i + 1}/{total})", fraction=(i + 1) / total if total else 1.0))

        findings = app_discovery.discover_app_storage_paths(name, try_llm_fallback=try_llm_fallback)
        if not findings:
            continue

        top = findings[0]
        classification = path_classifier.classify_path(top.path)
        advice = category_advisor.advice_for(classification.category, classification.known_service)
        if advice is None:
            continue

        # Only walk the filesystem for a path that's actually going to be
        # shown -- this is the one potentially slow step (a real service's
        # data directory can be huge), so it's deferred until every cheaper
        # filter above has already passed.
        size_bytes = path_size_bytes(top.path)

        suggestions.append(
            AppSuggestion(
                app_name=name,
                path=top.path,
                confidence=top.confidence,
                source=top.source,
                detail=top.detail,
                category=classification.category,
                known_service=classification.known_service,
                advice=advice,
                size_bytes=size_bytes,
                severity=severity_for_size(size_bytes),
            )
        )

    # The biggest storage consumers surface first -- severity (how much
    # disk it's actually using) matters more here than how confidently
    # the path was discovered.
    severity_rank = {SEVERITY_CRITICAL: 2, SEVERITY_LARGE: 1, SEVERITY_NORMAL: 0}
    suggestions.sort(key=lambda s: (severity_rank[s.severity], s.confidence), reverse=True)
    return suggestions
