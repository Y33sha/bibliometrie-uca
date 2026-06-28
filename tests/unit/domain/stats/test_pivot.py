"""Validation et grain du registre de pivot (pur, sans base)."""

import pytest

from domain.errors import ValidationError
from domain.stats.pivot import (
    DIMENSIONS,
    MEASURES,
    Dimension,
    applicable_facets,
    grain_multiplies,
    validate_pivot,
)


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


def test_validate_rejects_non_groupable_dimension():
    # `apc` est filtrable mais pas un axe de ventilation.
    assert DIMENSIONS["apc"].groupable is False
    with pytest.raises(ValidationError):
        validate_pivot("pub_count", ["apc"])


def test_validate_allows_lab_grouping():
    # Le laboratoire (forte cardinalité) est groupable : il sert d'axe de comparaison.
    assert DIMENSIONS["lab"].cardinality == "high"
    _, dims = validate_pivot("pub_count", ["lab"])
    assert [d.key for d in dims] == ["lab"]


class TestApplicableFacets:
    def test_universal_set_minus_nothing(self):
        # Sans groupement catégoriel : toutes les dimensions filtrables.
        facets = applicable_facets("pub_count", ["year"])
        assert set(facets) == {"year", "oa_voie", "doc_type", "lab", "apc"}

    def test_rule_g_categorical_grouping_leaves(self):
        # Grouper par voie OA la retire des facettes ; l'année ordinale, elle, reste.
        facets = applicable_facets("pub_count", ["year", "oa_voie"])
        assert "oa_voie" not in facets
        assert "year" in facets

    def test_non_filterable_dimension_never_a_facet(self):
        # `oa_access` est groupable mais pas filtrable : jamais dans la barre.
        assert DIMENSIONS["oa_access"].filterable is False
        assert "oa_access" not in applicable_facets("pub_count", [])


def test_grain_multiplies_only_for_multiplying_dimensions():
    # Aucune dimension groupable du registre ne démultiplie ; on en construit une (cas labo/sujet).
    multiplying = Dimension(
        "lab2", "Labo", "high",
        ordinal=False, multiplies=True, groupable=True, comparable=True, filterable=True,
    )
    assert grain_multiplies([DIMENSIONS["year"], DIMENSIONS["oa_access"]]) is False
    assert grain_multiplies([multiplying]) is True
    assert grain_multiplies([DIMENSIONS["year"], multiplying]) is True
