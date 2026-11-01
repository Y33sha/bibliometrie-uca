"""Filtre par sujets de la liste des publications : une publication est retenue si elle a un sujet d'au moins un des libellés normalisés cochés."""

from infrastructure.read_models.filters import subject_clause


def test_subject_clause_none_without_subject():
    assert subject_clause([]) is None


def test_subject_clause_retains_any_of_the_subjects():
    clause = subject_clause(["chimie", "biologie vegetale"])
    assert clause is not None
    assert "s.label_normalized = ANY(" in clause.sql
    assert clause.binds == {"flt_subject_labels": ["chimie", "biologie vegetale"]}
