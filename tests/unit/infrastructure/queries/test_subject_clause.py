"""Filtre par sujets de la liste des publications : une publication est retenue si elle porte au moins un des sujets cochés, comme pour les autres cases à cocher."""

from infrastructure.read_models.filters import subject_clause


def test_subject_clause_none_without_subject():
    assert subject_clause([]) is None


def test_subject_clause_retains_any_of_the_subjects():
    clause = subject_clause([3, 5])
    assert clause is not None
    assert "ANY(" in clause.sql
    assert clause.binds == {"flt_subject_ids": [3, 5]}
