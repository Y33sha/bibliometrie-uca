"""Filtre par langues de la liste des publications : une publication est retenue si sa langue est l'une des langues cochées."""

from infrastructure.read_models.filters import language_clause


def test_language_clause_none_without_language():
    assert language_clause([]) is None


def test_language_clause_retains_any_of_the_languages():
    clause = language_clause(["en", "fr"])
    assert clause is not None
    assert "ANY(" in clause.sql
    assert clause.binds == {"flt_languages": ["en", "fr"]}
