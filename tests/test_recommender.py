from storage_ai.models import DuplicateGroup, StorageForecast, UnusedCandidate
from storage_ai.recommender import UNUSED_SCORE_THRESHOLD, build_recommendations


def _forecast(days_until_full=None, source="snapshots"):
    return StorageForecast(
        current_total_bytes=10_000,
        free_bytes=5_000,
        bytes_per_day=100.0,
        days_until_full=days_until_full,
        projected_30_day_bytes=13_000,
        history_source=source,
    )


def test_duplicate_group_becomes_recommendation():
    group = DuplicateGroup(file_hash="abc", size=1000, files=["/a", "/b"], keep="/a")

    recs = build_recommendations([group], [], _forecast())

    assert len(recs) == 1
    assert recs[0].kind == "delete_duplicate"
    assert recs[0].targets == ["/b"]
    assert recs[0].estimated_savings_bytes == 1000


def test_unused_candidate_below_threshold_excluded():
    low = UnusedCandidate("/low", 500, 10, 10, UNUSED_SCORE_THRESHOLD - 0.1, "reason")
    high = UnusedCandidate("/high", 500, 300, 300, UNUSED_SCORE_THRESHOLD + 0.1, "reason")

    recs = build_recommendations([], [low, high], _forecast())

    assert len(recs) == 1
    assert recs[0].targets == ["/high"]


def test_storage_warning_only_within_horizon():
    recs_far = build_recommendations([], [], _forecast(days_until_full=365))
    recs_near = build_recommendations([], [], _forecast(days_until_full=10))

    assert not any(r.kind == "storage_warning" for r in recs_far)
    assert any(r.kind == "storage_warning" for r in recs_near)


def test_recommendations_sorted_by_savings_with_warning_last():
    group = DuplicateGroup(file_hash="abc", size=1000, files=["/a", "/b"], keep="/a")
    high_unused = UnusedCandidate("/high", 5000, 300, 300, 0.9, "reason")

    recs = build_recommendations([group], [high_unused], _forecast(days_until_full=5))

    assert recs[0].targets == ["/high"]
    assert recs[-1].kind == "storage_warning"
