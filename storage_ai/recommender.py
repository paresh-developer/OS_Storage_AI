"""Turns raw analysis results into a ranked, actionable recommendation list."""

from __future__ import annotations

from storage_ai.config import STORAGE_WARNING_HORIZON_DAYS
from storage_ai.models import (
    DuplicateGroup,
    Recommendation,
    StorageForecast,
    UnusedCandidate,
)
from storage_ai.utils import human_size as _human_size

UNUSED_SCORE_THRESHOLD = 0.6


def build_recommendations(
    duplicate_groups: list[DuplicateGroup],
    unused_candidates: list[UnusedCandidate],
    forecast: StorageForecast,
    category_recommendations: list[Recommendation] | None = None,
) -> list[Recommendation]:
    recommendations: list[Recommendation] = []

    for group in duplicate_groups:
        removable = [f for f in group.files if f != group.keep]
        recommendations.append(
            Recommendation(
                kind="delete_duplicate",
                title=f"{len(removable)} duplicate copy(ies) of a {_human_size(group.size)} file",
                detail=f"Identical to kept copy: {group.keep}",
                estimated_savings_bytes=group.wasted_space,
                confidence=1.0,
                targets=removable,
            )
        )

    for candidate in unused_candidates:
        if candidate.score < UNUSED_SCORE_THRESHOLD:
            continue
        recommendations.append(
            Recommendation(
                kind="archive_unused",
                title=f"Likely unused: {_human_size(candidate.size)} file",
                detail=f"{candidate.path} -- {candidate.reason}",
                estimated_savings_bytes=candidate.size,
                confidence=candidate.score,
                targets=[candidate.path],
            )
        )

    if forecast.days_until_full is not None and forecast.days_until_full <= STORAGE_WARNING_HORIZON_DAYS:
        recommendations.append(
            Recommendation(
                kind="storage_warning",
                title=f"Free space projected to run out in ~{int(forecast.days_until_full)} days",
                detail=(
                    f"Growing at {_human_size(forecast.bytes_per_day)}/day "
                    f"(forecast source: {forecast.history_source})"
                ),
                estimated_savings_bytes=0,
                confidence=0.7 if forecast.history_source == "file-timestamps" else 0.9,
                targets=[],
            )
        )

    if category_recommendations:
        recommendations.extend(category_recommendations)

    recommendations.sort(key=lambda r: (r.kind == "storage_warning", -r.estimated_savings_bytes))
    return recommendations
