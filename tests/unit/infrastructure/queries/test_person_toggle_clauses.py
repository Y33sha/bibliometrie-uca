"""Facettes binaires yes/no liées à une personne (`corresponding`, `in_perimeter`).

Régression : cocher les deux valeurs (`yes,no`) tombait dans un cas non prévu —
`in_perimeter` basculait à tort sur la seule branche `no`, n'affichant que le
hors-périmètre au lieu de tout. Le découpage se fait côté routeur ; la clause
reçoit une `list[str]`.
"""

from infrastructure.queries.filters import (
    corresponding_clause,
    in_perimeter_person_clause,
)


def test_corresponding_none_without_person_or_filter():
    assert corresponding_clause(0, ["yes"]) is None
    assert corresponding_clause(42, []) is None


def test_corresponding_yes_is_exists():
    clause = corresponding_clause(42, ["yes"])
    assert clause is not None
    assert clause.sql.startswith("EXISTS")
    assert clause.binds == {"flt_corr_person": 42}


def test_corresponding_no_is_negated():
    clause = corresponding_clause(42, ["no"])
    assert clause is not None
    assert clause.sql.startswith("NOT EXISTS")


def test_corresponding_both_is_no_constraint():
    clause = corresponding_clause(42, ["yes", "no"])
    assert clause is not None
    assert " OR " in clause.sql
    assert "EXISTS" in clause.sql and "NOT EXISTS" in clause.sql


def test_corresponding_unknown_value_ignored():
    assert corresponding_clause(42, ["bogus"]) is None


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
    # Régression : `yes,no` basculait à tort sur la seule branche NOT EXISTS.
    clause = in_perimeter_person_clause(["yes", "no"], 42)
    assert clause is not None
    assert " OR " in clause.sql
    assert "EXISTS" in clause.sql and "NOT EXISTS" in clause.sql
