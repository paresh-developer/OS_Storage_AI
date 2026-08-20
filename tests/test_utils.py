import pytest

from storage_ai.utils import human_duration_days, human_duration_seconds, human_size


@pytest.mark.parametrize(
    "num_bytes,expected",
    [
        (500, "500.0 B"),
        (2048, "2.0 KB"),
        (5 * 1024**2, "5.0 MB"),
        (3 * 1024**3, "3.0 GB"),
    ],
)
def test_human_size(num_bytes, expected):
    assert human_size(num_bytes) == expected


@pytest.mark.parametrize(
    "days,expected_unit",
    [
        (0.001, "less than an hour"),
        (0.5, "hour"),
        (5, "day"),
        (45, "day"),
        (200, "month"),
        (900, "year"),
        (627490, "decade"),
    ],
)
def test_human_duration_days_picks_the_right_unit(days, expected_unit):
    result = human_duration_days(days)
    assert expected_unit in result


def test_human_duration_days_large_value_is_far_shorter_than_raw_days():
    result = human_duration_days(627490)
    assert result == "171.8 decades"


def test_human_duration_days_small_values_stay_in_days():
    assert human_duration_days(1) == "1 day"
    assert human_duration_days(2) == "2 days"


@pytest.mark.parametrize(
    "seconds,expected_unit",
    [
        (0.4, "less than a second"),
        (30, "second"),
        (90, "minute"),
        (7200, "hour"),
    ],
)
def test_human_duration_seconds_picks_the_right_unit(seconds, expected_unit):
    assert expected_unit in human_duration_seconds(seconds)


def test_human_duration_seconds_exact_values():
    assert human_duration_seconds(45) == "45 seconds"
    assert human_duration_seconds(90) == "1.5 minutes"
    assert human_duration_seconds(7200) == "2.0 hours"
