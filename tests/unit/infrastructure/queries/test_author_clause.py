"""Filtre par auteur de la liste des publications.

Sur la page d'une personne, la personne et l'auteur choisi en facette filtrent ensemble (publications cosignées). Les deux clauses lient donc des paramètres distincts.
"""

from infrastructure.read_models.filters import author_clause, person_clause


def test_author_clause_none_without_author():
    assert author_clause(None) is None


def test_author_and_person_clauses_bind_distinct_parameters():
    author = author_clause(2)
    assert author is not None
    assert author.binds == {"flt_author_id": 2}
    assert set(author.binds).isdisjoint(person_clause(1).binds)
