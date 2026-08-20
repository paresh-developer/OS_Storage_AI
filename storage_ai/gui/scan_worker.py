"""Runs the analysis pipeline on a background thread so the UI stays
responsive during a scan of a large directory tree."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from storage_ai.pipeline import AnalysisResult, run_analysis


class ScanWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)  # AnalysisResult
    failed = Signal(str)

    def __init__(self, root: str) -> None:
        super().__init__()
        self._root = root

    def run(self) -> None:
        try:
            result: AnalysisResult = run_analysis(self._root, on_progress=self.progress.emit)
        except Exception as exc:  # surfaced to the user rather than crashing the app
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


def start_scan(root: str, on_progress, on_finished, on_failed) -> tuple[QThread, ScanWorker]:
    """Wires up a worker+thread pair and starts it. Caller must keep the
    returned thread/worker alive (e.g. as attributes on the main window)
    until `finished`/`failed` fires."""
    thread = QThread()
    worker = ScanWorker(root)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)

    thread.start()
    return thread, worker
