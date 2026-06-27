"""Validation et grain du registre de pivot (pur, sans base)."""

import pytest

from domain.errors import ValidationError
from domain.stats.pivot import DIMENSIONS, MEASURES, grain_multiplies, validate_pivot


def test_validate_returns_measure_and_dimensions():
    measure, dims = validate_pivot("pub_count", ["year", "oa_access"])
    assert measure is MEASURES["pub_count"]
    assert [d.key for d in dims] == ["year", "oa_access"]


def test_validate_allows_zero_groups():
    measure, dims = validate_pivot("pub_count", [])
    assert measure.key == "pub_count"
    assert dims == []


def test_validate_rejects_unknown_measure():
    with pytest.raises(ValidationError):
        validate_pivot("bogus", ["year"])


def test_validate_rejects_unknown_dimension():
    with pytest.raises(ValidationError):
        validate_pivot("pub_count", ["bogus"])


def test_validate_rejects_repeated_group():
    with pytest.raises(ValidationError):
        validate_pivot("pub_count", ["year", "year"])


def test_grain_multiplies_only_for_multiplying_dimensions():
    assert grain_multiplies([DIMENSIONS["source"]]) is True
    assert grain_multiplies([DIMENSIONS["year"], DIMENSIONS["oa_access"]]) is False
    assert grain_multiplies([DIMENSIONS["year"], DIMENSIONS["source"]]) is True
