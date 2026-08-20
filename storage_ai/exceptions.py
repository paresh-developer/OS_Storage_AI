"""Shared exception types used across the analysis pipeline."""

from __future__ import annotations


class ScanCancelled(Exception):
    """Raised from inside the pipeline when a cancel_check callback reports
    that the user asked to stop; caught by the GUI layer (scan_worker.py)
    to distinguish a deliberate cancellation from a real error."""
