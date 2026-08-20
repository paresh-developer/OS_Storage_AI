"""K-means clustering of files by size and staleness.

This is deliberately independent of unused.py's classifier: that model is
trained toward a specific "is this unused" label (weak-supervised), while
this has no labels at all -- it just finds natural groupings in (size,
days-since-access) space. When a file lands in the same "large and stale"
territory under both techniques, that agreement is a stronger signal than
either alone; when this module is the only thing built here, it also gives
a genuinely different lens for the report (unsupervised clustering,
alongside the classification and regression already in the project).

Cluster labels are assigned relative to this scan's own overall median size
and staleness (not fixed thresholds), so "large" and "stale" mean something
sensible whether the folder is a code repo or a Downloads folder.
"""

from __future__ import annotations

import math
import statistics
import time
import warnings
from dataclasses import dataclass

from sklearn.cluster import KMeans
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import StandardScaler

from storage_ai.models import FileRecord

_SECONDS_PER_DAY = 86400
_MIN_FILES_PER_CLUSTER = 3


@dataclass
class ClusterPoint:
    path: str
    size: int
    days_since_access: float
    cluster_id: int


@dataclass
class ClusterSummary:
    cluster_id: int
    label: str
    file_count: int
    total_size: int
    median_size: float
    median_days_since_access: float


@dataclass
class ClusteringResult:
    points: list[ClusterPoint]
    summaries: list[ClusterSummary]


def cluster_files(
    records: list[FileRecord],
    now: float | None = None,
    max_clusters: int = 3,
) -> ClusteringResult | None:
    """Returns None when there's too little data for clusters to mean
    anything (fewer than 2 * MIN_FILES_PER_CLUSTER files)."""
    if len(records) < 2 * _MIN_FILES_PER_CLUSTER:
        return None

    now = time.time() if now is None else now
    n_clusters = min(max_clusters, len(records) // _MIN_FILES_PER_CLUSTER)

    log_sizes = [math.log1p(r.size) for r in records]
    days_since_access = [max(0.0, (now - r.accessed_time) / _SECONDS_PER_DAY) for r in records]
    features = list(zip(log_sizes, days_since_access))

    scaled = StandardScaler().fit_transform(features)
    with warnings.catch_warnings():
        # Small or duplicate-heavy scans can legitimately have fewer natural
        # clusters than requested -- expected, not something to surface.
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        cluster_ids = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(scaled)

    points = [
        ClusterPoint(path=r.path, size=r.size, days_since_access=days_since_access[i], cluster_id=int(cluster_ids[i]))
        for i, r in enumerate(records)
    ]

    return ClusteringResult(points=points, summaries=_summarize(points))


def _summarize(points: list[ClusterPoint]) -> list[ClusterSummary]:
    overall_median_size = statistics.median(p.size for p in points)
    overall_median_days = statistics.median(p.days_since_access for p in points)

    summaries = []
    for cluster_id in sorted({p.cluster_id for p in points}):
        members = [p for p in points if p.cluster_id == cluster_id]
        median_size = statistics.median(m.size for m in members)
        median_days = statistics.median(m.days_since_access for m in members)
        size_word = "Large" if median_size >= overall_median_size else "Small"
        age_word = "Stale" if median_days >= overall_median_days else "Active"
        summaries.append(
            ClusterSummary(
                cluster_id=cluster_id,
                label=f"{size_word} & {age_word}",
                file_count=len(members),
                total_size=sum(m.size for m in members),
                median_size=median_size,
                median_days_since_access=median_days,
            )
        )
    return summaries
