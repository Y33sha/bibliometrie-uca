"""Facettes liées à une personne : position d'auteur et périmètre.

La clause reçoit la liste des valeurs cochées, découpée par le routeur. Les valeurs cochées se combinent par OR.
"""

from infrastructure.read_models.filters import (
    author_position_clause,
    in_perimeter_person_clause,
)


def test_author_position_none_without_person_or_filter():
    assert author_position_clause(0, ["corresponding"]) is None
    assert author_position_clause(42, []) is None


def test_author_position_corresponding_is_exists():
    clause = author_position_clause(42, ["corresponding"])
    assert clause is not None
    assert clause.sql.startswith("(EXISTS")
    assert clause.binds == {"flt_position_person": 42}


def test_author_position_other_is_negated():
    clause = author_position_clause(42, ["other"])
    assert clause is not None
    assert clause.sql.startswith("(NOT (EXISTS")


def test_author_position_values_combine_with_or():
    clause = author_position_clause(42, ["corresponding", "other"])
    assert clause is not None
    assert " OR NOT (" in clause.sql


def test_in_perimeter_none_without_person_or_filter():
    assert in_perimeter_person_clause(["yes"], None) is None
    assert in_perimeter_person_clause([], 42) is None


def test_in_perimeter_yes_is_exists():
    clause = in_perimeter_person_clause(["yes"], 42)
    assert clause is not None
    assert clause.sql.startswith("EXISTS")
    assert clause.binds == {"flt_in_per_person": 42}


def test_in_perimeter_no_is_negated():
    clause = in_perimeter_person_clause(["no"], 42)
    assert clause is not None
    assert clause.sql.startswith("NOT EXISTS")


def test_in_perimeter_both_selected_shows_all_not_just_out():
    clause = in_perimeter_person_clause(["yes", "no"], 42)
    assert clause is not None
    assert " OR " in clause.sql
    assert "EXISTS" in clause.sql and "NOT EXISTS" in clause.sql
