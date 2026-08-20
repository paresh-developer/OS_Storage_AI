from storage_ai.clustering import cluster_files
from storage_ai.models import FileRecord

DAY = 86400


def _record(path, size, days_since_access):
    now = 0.0
    return FileRecord(
        path=path,
        size=size,
        extension=".dat",
        created_time=now - days_since_access * DAY,
        modified_time=now - days_since_access * DAY,
        accessed_time=now - days_since_access * DAY,
        depth=1,
    )


def test_returns_none_with_too_few_files():
    records = [_record(f"/f{i}.dat", 1000, 1) for i in range(4)]
    assert cluster_files(records, now=0.0) is None


def test_separates_large_stale_from_small_active():
    large_stale = [_record(f"/large_stale{i}.dat", 500_000_000, 400) for i in range(10)]
    small_active = [_record(f"/small_active{i}.dat", 500, 1) for i in range(10)]

    result = cluster_files(large_stale + small_active, now=0.0)

    assert result is not None
    points_by_path = {p.path: p for p in result.points}
    large_cluster_ids = {points_by_path[f"/large_stale{i}.dat"].cluster_id for i in range(10)}
    small_cluster_ids = {points_by_path[f"/small_active{i}.dat"].cluster_id for i in range(10)}

    assert len(large_cluster_ids) == 1
    assert len(small_cluster_ids) == 1
    assert large_cluster_ids != small_cluster_ids

    labels = {s.cluster_id: s.label for s in result.summaries}
    assert labels[large_cluster_ids.pop()] == "Large & Stale"
    assert labels[small_cluster_ids.pop()] == "Small & Active"


def test_cluster_count_is_capped_by_max_clusters():
    records = [_record(f"/f{i}.dat", 1000 * (i + 1), i * 10) for i in range(40)]

    result = cluster_files(records, now=0.0, max_clusters=3)

    assert result is not None
    assert len({p.cluster_id for p in result.points}) <= 3
    assert len(result.summaries) <= 3


def test_every_file_is_assigned_to_exactly_one_cluster():
    records = [_record(f"/f{i}.dat", 1000 * (i + 1), i) for i in range(12)]

    result = cluster_files(records, now=0.0)

    assert len(result.points) == len(records)
    assert {p.path for p in result.points} == {r.path for r in records}
