"""Runs batch application-storage-path discovery on a background thread,
mirroring scan_worker.py's worker/thread pattern -- checking every running
process can take a user-noticeable amount of time and must stay
cancellable, same reasoning as a folder scan."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal

from storage_ai.app_suggestions import AppSuggestion, discover_running_app_suggestions
from storage_ai.exceptions import ScanCancelled


class AppSuggestionsWorker(QObject):
    progress = Signal(object)  # ScanProgress
    finished = Signal(list)  # list[AppSuggestion]
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, try_llm_fallback: bool = True) -> None:
        super().__init__()
        self._try_llm_fallback = try_llm_fallback
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Thread-safe: called from the GUI thread while `run` executes on
        the worker thread."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            suggestions: list[AppSuggestion] = discover_running_app_suggestions(
                on_progress=self.progress.emit,
                cancel_check=self._cancel_event.is_set,
                try_llm_fallback=self._try_llm_fallback,
            )
        except ScanCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:  # surfaced to the user rather than crashing the app
            self.failed.emit(str(exc))
            return
        self.finished.emit(suggestions)


def start_app_suggestions_scan(on_progress, on_finished, on_failed, on_cancelled, try_llm_fallback: bool = True):
    """Wires up a worker+thread pair and starts it. Caller must keep the
    returned thread/worker alive until finished/failed/cancelled fires."""
    thread = QThread()
    worker = AppSuggestionsWorker(try_llm_fallback=try_llm_fallback)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.cancelled.connect(on_cancelled)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.cancelled.connect(thread.quit)

    thread.start()
    return thread, worker
