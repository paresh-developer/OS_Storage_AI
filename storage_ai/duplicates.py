"""Exact-duplicate detection via a three-stage funnel.

Files are grouped by (1) size, then (2) a partial hash of the first 4KB,
then (3) a full SHA-256 hash -- each stage only runs on the survivors of the
previous one. This avoids fully hashing files that can't possibly be
duplicates (different size) or almost certainly aren't (different partial
hash), which matters a lot once a tree has tens of thousands of files.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from storage_ai.config import MIN_DUPLICATE_SIZE_BYTES
from storage_ai.exceptions import ScanCancelled
from storage_ai.hashing import full_hash, partial_hash
from storage_ai.models import DuplicateGroup, FileRecord


def _choose_keeper(paths: list[str], created_times: dict[str, float]) -> str:
    """Keep the oldest copy by default -- it's the one least likely to be a
    stray re-download or a copy created by an app's "save as" flow."""
    return min(paths, key=lambda p: created_times.get(p, float("inf")))


def find_duplicates(
    records: list[FileRecord],
    min_size: int = MIN_DUPLICATE_SIZE_BYTES,
    cancel_check: Callable[[], bool] | None = None,
) -> list[DuplicateGroup]:
    by_size: dict[int, list[FileRecord]] = defaultdict(list)
    for record in records:
        if record.size >= min_size:
            by_size[record.size].append(record)

    groups: list[DuplicateGroup] = []

    for size, same_size_records in by_size.items():
        if cancel_check is not None and cancel_check():
            raise ScanCancelled()
        if len(same_size_records) < 2:
            continue

        by_partial: dict[str, list[FileRecord]] = defaultdict(list)
        for record in same_size_records:
            digest = partial_hash(record.path)
            if digest is not None:
                by_partial[digest].append(record)

        for partial_group in by_partial.values():
            if len(partial_group) < 2:
                continue

            by_full: dict[str, list[FileRecord]] = defaultdict(list)
            for record in partial_group:
                digest = full_hash(record.path)
                if digest is not None:
                    by_full[digest].append(record)

            for file_hash, full_group in by_full.items():
                if len(full_group) < 2:
                    continue
                paths = [r.path for r in full_group]
                created_times = {r.path: r.created_time for r in full_group}
                groups.append(
                    DuplicateGroup(
                        file_hash=file_hash,
                        size=size,
                        files=paths,
                        keep=_choose_keeper(paths, created_times),
                    )
                )

    groups.sort(key=lambda g: g.wasted_space, reverse=True)
    return groups
