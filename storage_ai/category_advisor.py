"""Static advisory recommendations keyed to a path category or known
service -- explicitly NOT config-file parsing or editing. This suggests the
kind of thing a human administrator would already know to try (log
rotation, cache clearing, image pruning) without reading or writing any
live service's actual configuration. Editing a running database's config
is a different risk class than trashing a stale PDF -- getting it wrong can
mean data loss or a service that won't restart -- so this stays advisory
text only, same as every other recommendation in this app.
"""

from __future__ import annotations

from storage_ai.models import Recommendation
from storage_ai.path_classifier import CATEGORY_CACHE, CATEGORY_LOG, CATEGORY_TRASH
from storage_ai.utils import human_size

_CATEGORY_ADVICE = {
    CATEGORY_LOG: "Log files are usually safe to rotate or truncate without affecting the running application.",
    CATEGORY_CACHE: "Cache directories are safe to clear -- the owning application regenerates them as needed.",
    CATEGORY_TRASH: "Emptying this permanently deletes its contents and reclaims the space immediately.",
}

_SERVICE_ADVICE = {
    "PostgreSQL": (
        "Consider tuning log_rotation_size/log_rotation_age in postgresql.conf, or lowering "
        "log_min_duration_statement if query logging dominates the growth."
    ),
    "MongoDB": "Consider MongoDB's built-in log rotation (the logRotate command, or sending SIGUSR1 to mongod).",
    "MySQL": "Consider enabling binlog_expire_logs_seconds, and rotating the general/slow query logs.",
    "MariaDB": "Consider enabling binlog_expire_logs_seconds, and rotating the general/slow query logs.",
    "Docker": "`docker system prune` reclaims unused images, stopped containers, and build cache layers.",
    "Redis": "Review the appendonly/save settings -- AOF/RDB files grow with write volume.",
    "Elasticsearch": "Review index lifecycle management (ILM) policies -- old indices are a common unbounded-growth source.",
}

# Below this, an advisory isn't worth surfacing -- it would just be noise.
_MIN_ADVISORY_BYTES = 100 * 1024 * 1024


def build_category_recommendations(category_totals: dict[tuple[str, str | None], int]) -> list[Recommendation]:
    """`category_totals` maps (category, known_service) -> total bytes, as
    produced by pipeline.py from the per-file classifications."""
    recommendations = []
    for (category, service), total_bytes in category_totals.items():
        if total_bytes < _MIN_ADVISORY_BYTES:
            continue
        advice = _SERVICE_ADVICE.get(service) if service else _CATEGORY_ADVICE.get(category)
        if advice is None:
            continue
        subject = service or category.replace("_", " ")
        recommendations.append(
            Recommendation(
                kind="category_advisory",
                title=f"{human_size(total_bytes)} in {subject}",
                detail=advice,
                estimated_savings_bytes=0,
                confidence=0.6,
                targets=[],
            )
        )
    return recommendations
