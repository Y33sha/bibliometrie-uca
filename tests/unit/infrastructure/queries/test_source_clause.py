"""Filtre par présence dans les sources de la liste des publications : `hal_yes` retient les publications présentes dans HAL, `hal_no` les autres."""

from infrastructure.read_models.filters import source_clause


def test_source_clause_none_without_value():
    assert source_clause([]) is None


def test_source_clause_combines_presence_and_absence():
    clause = source_clause(["hal_yes", "openalex_no"])
    assert clause is not None
    assert clause.sql == (
        "p.sources @> ARRAY['hal'::source_type] AND NOT p.sources @> ARRAY['openalex'::source_type]"
    )


def test_source_clause_ignores_values_outside_the_vocabulary():
    assert source_clause(["crossref_yes", "hal_maybe", "hal"]) is None
