"""Streaming file hashing used to confirm byte-for-byte duplicates.

Two tiers are provided so duplicate detection never has to fully hash every
file in a tree (see duplicates.py for how they're combined):

1. partial_hash - hashes only the first few KB. Cheap, and enough to rule
   out almost all false positives from a same-size grouping.
2. full_hash - hashes the entire file, streamed in chunks so memory use
   stays flat regardless of file size.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 65536
_PARTIAL_BYTES = 4096


def partial_hash(path: str | Path) -> str | None:
    try:
        with open(path, "rb") as handle:
            data = handle.read(_PARTIAL_BYTES)
        return hashlib.sha256(data).hexdigest()
    except OSError:
        return None


def full_hash(path: str | Path) -> str | None:
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(_CHUNK_SIZE):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None
