"""Lots de publications de la phase `author_grouping`."""

from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.author_grouping.author_grouping import (
    publication_batches,
)


def test_un_lot_se_ferme_au_plafond_de_signatures(monkeypatch):
    monkeypatch.setattr(author_grouping, "BATCH_SIGNATURES", 100)
    publications = [(1, 10), (2, 60), (3, 40), (4, 5), (5, 300), (6, 1)]
    assert publication_batches(publications) == [[1, 2, 3], [4, 5], [6]]


def test_un_lot_se_ferme_au_plafond_de_publications(monkeypatch):
    monkeypatch.setattr(author_grouping, "BATCH_SIZE", 2)
    assert publication_batches([(1, 1), (2, 1), (3, 1)]) == [[1, 2], [3]]
