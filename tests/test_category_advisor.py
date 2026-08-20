from storage_ai.category_advisor import build_category_recommendations
from storage_ai.path_classifier import CATEGORY_APPLICATION_DATA, CATEGORY_LOG, CATEGORY_OTHER, CATEGORY_USER_DATA

GB = 1024**3


def test_large_known_service_gets_service_specific_advice():
    totals = {(CATEGORY_APPLICATION_DATA, "PostgreSQL"): 2 * GB}
    [rec] = build_category_recommendations(totals)

    assert rec.kind == "category_advisory"
    assert "PostgreSQL" in rec.title
    assert "postgresql.conf" in rec.detail or "log_rotation" in rec.detail
    assert rec.estimated_savings_bytes == 0


def test_large_log_category_gets_generic_advice():
    totals = {(CATEGORY_LOG, None): 2 * GB}
    [rec] = build_category_recommendations(totals)

    assert "Logs" in rec.title or "log" in rec.title.lower()
    assert "rotate" in rec.detail.lower()


def test_small_totals_are_not_surfaced():
    totals = {(CATEGORY_LOG, None): 1024}
    assert build_category_recommendations(totals) == []


def test_categories_without_advice_are_skipped():
    totals = {(CATEGORY_OTHER, None): 5 * GB, (CATEGORY_USER_DATA, None): 5 * GB}
    assert build_category_recommendations(totals) == []


def test_unknown_service_falls_back_to_no_advice_if_not_in_lookup():
    totals = {(CATEGORY_APPLICATION_DATA, "SomeObscureDB"): 2 * GB}
    assert build_category_recommendations(totals) == []
