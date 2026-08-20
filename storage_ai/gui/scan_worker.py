"""Runs the analysis pipeline on a background thread so the UI stays
responsive during a scan of a large directory tree, and can be cancelled
mid-scan."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal

from storage_ai.exceptions import ScanCancelled
from storage_ai.pipeline import AnalysisResult, run_analysis


class ScanWorker(QObject):
    progress = Signal(object)  # ScanProgress
    finished = Signal(object)  # AnalysisResult
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, root: str) -> None:
        super().__init__()
        self._root = root
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Thread-safe: called from the GUI thread while `run` executes on
        the worker thread. Cancellation is cooperative -- the pipeline
        checks this between files/groups rather than being killed
        instantly, so there can be a brief delay before `cancelled` fires."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result: AnalysisResult = run_analysis(
                self._root,
                on_progress=self.progress.emit,
                cancel_check=self._cancel_event.is_set,
            )
        except ScanCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:  # surfaced to the user rather than crashing the app
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


def start_scan(root: str, on_progress, on_finished, on_failed, on_cancelled) -> tuple[QThread, ScanWorker]:
    """Wires up a worker+thread pair and starts it. Caller must keep the
    returned thread/worker alive (e.g. as attributes on the main window)
    until `finished`/`failed`/`cancelled` fires."""
    thread = QThread()
    worker = ScanWorker(root)
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
