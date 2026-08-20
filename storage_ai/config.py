"""Central configuration and tunable thresholds.

Kept in one place so the methodology write-up can cite exact values.
"""

from __future__ import annotations

from pathlib import Path

APP_DIR = Path.home() / ".storage_ai"
DB_PATH = APP_DIR / "storage_ai.sqlite3"
ARCHIVE_DIR = APP_DIR / "archive"

# Directories skipped during a scan regardless of root chosen.
DEFAULT_EXCLUDES = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "$RECYCLE.BIN",
    "System Volume Information",
}

# Files smaller than this are ignored for duplicate hashing (not worth the I/O).
MIN_DUPLICATE_SIZE_BYTES = 4096

# Absolute top-level virtual/kernel filesystems -- never walked, regardless
# of DEFAULT_EXCLUDES above (which matches by name anywhere in the tree,
# not by a rooted absolute path -- a project could legitimately have a
# subfolder literally named "proc"). Only meaningful when a scan root is
# high enough in the tree to reach these (e.g. "/" or "/var"); a normal
# home-directory scan never encounters them. Windows has no equivalent --
# its virtual-ish paths ($RECYCLE.BIN, System Volume Information) are
# already name-matched above.
LINUX_VIRTUAL_FS_ROOTS = {"/proc", "/sys", "/dev", "/run"}

# A file is a confident "unused" example if untouched this long.
UNUSED_CONFIDENT_DAYS = 180
# A file is a confident "active" example if touched this recently.
ACTIVE_CONFIDENT_DAYS = 7

# Minimum labeled examples per class before the unused-file classifier trains;
# below this the tool falls back to the pure heuristic score.
MIN_TRAINING_SAMPLES_PER_CLASS = 20

# Recommendation surfaced when the storage forecast projects exhaustion within.
STORAGE_WARNING_HORIZON_DAYS = 30

FILE_TYPE_CATEGORIES: dict[str, set[str]] = {
    "archive": {".zip", ".tar", ".gz", ".rar", ".7z", ".iso"},
    "installer": {".exe", ".msi", ".dmg", ".deb", ".rpm", ".appimage"},
    "media": {".mp4", ".mkv", ".mov", ".avi", ".mp3", ".flac", ".wav"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"},
    "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"},
    "temp": {".tmp", ".temp", ".log", ".cache", ".bak", ".old"},
    "code": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".go", ".rs"},
}


def categorize_extension(extension: str) -> str:
    ext = extension.lower()
    for category, extensions in FILE_TYPE_CATEGORIES.items():
        if ext in extensions:
            return category
    return "other"
