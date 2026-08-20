from storage_ai.models import FileRecord
from storage_ai.unused import score_files

DAY = 86400


def _record(path, days_since_access, days_since_modified=None, size=1000, ext=".dat"):
    days_since_modified = days_since_access if days_since_modified is None else days_since_modified
    now = 0.0
    return FileRecord(
        path=path,
        size=size,
        extension=ext,
        created_time=now - days_since_modified * DAY,
        modified_time=now - days_since_modified * DAY,
        accessed_time=now - days_since_access * DAY,
        depth=1,
    )


def test_stale_file_scores_higher_than_fresh_file():
    stale = _record("/stale.dat", days_since_access=300)
    fresh = _record("/fresh.dat", days_since_access=1)

    candidates = score_files([stale, fresh], now=0.0)
    scores = {c.path: c.score for c in candidates}

    assert scores["/stale.dat"] > scores["/fresh.dat"]


def test_falls_back_to_heuristic_with_too_few_labeled_examples():
    records = [_record(f"/f{i}.dat", days_since_access=90) for i in range(5)]

    candidates = score_files(records, now=0.0)

    for c in candidates:
        assert "heuristic" in c.reason


def test_classifier_trains_when_enough_confident_examples():
    unused = [_record(f"/old{i}.dat", days_since_access=200) for i in range(25)]
    active = [_record(f"/new{i}.dat", days_since_access=1) for i in range(25)]

    candidates = score_files(unused + active, now=0.0)
    scores = {c.path: c.score for c in candidates}

    assert all(scores[f"/old{i}.dat"] > scores[f"/new{i}.dat"] for i in range(25))


def test_results_sorted_descending_by_score():
    records = [_record(f"/f{i}.dat", days_since_access=i * 10) for i in range(10)]

    candidates = score_files(records, now=0.0)

    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)
