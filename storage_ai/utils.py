"""Small formatting helpers shared across the analysis and GUI layers."""

from __future__ import annotations


def human_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_duration_days(days: float) -> str:
    """Formats a day count in the coarsest unit that keeps it readable --
    hours, days, months, years, or decades -- instead of a raw day count
    that can run into the hundreds of thousands for slow-growing folders."""
    if days < 1:
        hours = days * 24
        if hours < 1:
            return "less than an hour"
        return f"{hours:.1f} hour{'s' if hours != 1 else ''}"
    if days < 60:
        return f"{days:.0f} day{'s' if days != 1 else ''}"
    months = days / 30.44
    if months < 24:
        return f"{months:.1f} month{'s' if months != 1 else ''}"
    years = days / 365.25
    if years < 100:
        return f"{years:.1f} year{'s' if years != 1 else ''}"
    decades = days / 3652.5
    return f"{decades:.1f} decade{'s' if decades != 1 else ''}"
