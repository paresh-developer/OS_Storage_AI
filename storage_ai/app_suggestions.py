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
docs/METHODOLOGY.md Section 8. The only new logic here is "which app names
to even ask about" (every distinct running process) and "is a discovered
path actually worth telling the user about" (does it classify into a
category/service with real advisory text, per category_advisor.py).
"""

from __future__ import annotations

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
            )
        )

    suggestions.sort(key=lambda s: s.confidence, reverse=True)
    return suggestions
