"""Validation du registre de pivot (pur, sans base)."""

import pytest

from domain.errors import ValidationError
from infrastructure.read_models.stats.pivot import (
    DIMENSIONS,
    MEASURES,
    validate_indicator,
    validate_pivot,
)


def test_validate_returns_measure_and_dimensions():
    measure, dims = validate_pivot("publication_count", ["year", "oa_access"])
    assert measure is MEASURES["publication_count"]
    assert [d.key for d in dims] == ["year", "oa_access"]


def test_validate_allows_zero_groups():
    measure, dims = validate_pivot("publication_count", [])
    assert measure.key == "publication_count"
    assert dims == []


def test_validate_rejects_unknown_measure():
    with pytest.raises(ValidationError, match="Mesure inconnue : 'bogus'"):
        validate_pivot("bogus", ["year"])


def test_validate_rejects_unknown_dimension():
    with pytest.raises(ValidationError, match="Dimension inconnue : 'bogus'"):
        validate_pivot("publication_count", ["bogus"])


def test_validate_rejects_repeated_group():
    with pytest.raises(ValidationError, match="Groupement répété : 'year'"):
        validate_pivot("publication_count", ["year", "year"])


def test_validate_allows_lab_grouping():
    # Le laboratoire (forte cardinalité) est groupable : il sert d'axe de comparaison.
    assert DIMENSIONS["lab"].cardinality == "high"
    _, dims = validate_pivot("publication_count", ["lab"])
    assert [d.key for d in dims] == ["lab"]


def test_indicator_without_comparison_groups_by_its_breakdown():
    assert validate_indicator("oa_access", "") == ("publication_count", ["oa_access"])


def test_indicator_imposes_its_measure():
    assert validate_indicator("apc_amount", "year") == ("apc_amount", ["oa_voie", "year"])


def test_indicator_rejects_unknown_key():
    with pytest.raises(ValidationError, match="Indicateur inconnu : 'bogus'"):
        validate_indicator("bogus", "")


@pytest.mark.parametrize("compare", ["bogus", "oa_access"])
def test_indicator_rejects_non_comparable_axis(compare):
    with pytest.raises(ValidationError, match=f"Axe de comparaison inconnu : '{compare}'"):
        validate_indicator("doc_type_grouped", compare)
