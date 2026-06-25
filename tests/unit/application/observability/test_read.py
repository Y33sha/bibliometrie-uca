"""Calculs de lecture : écart de durée au médian (sans base)."""

from application.observability.read import duration_ratio, median_duration


def test_median_duration():
    assert median_duration([3.0, 1.0, 2.0]) == 2.0
    assert median_duration([]) is None


def test_duration_ratio():
    assert duration_ratio(10.0, 5.0) == 2.0
    assert duration_ratio(10.0, None) is None
    assert duration_ratio(10.0, 0.0) is None
