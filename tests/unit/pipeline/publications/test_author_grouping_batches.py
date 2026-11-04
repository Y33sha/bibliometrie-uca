"""Lots de publications et écritures de la phase `author_grouping`."""

from pipeline.transformation.publications.author_grouping import author_grouping
from pipeline.transformation.publications.author_grouping.author_grouping import (
    membership_changes,
    publication_batches,
)
from pipeline.transformation.publications.author_grouping.store import MembershipRow


def test_un_lot_se_ferme_au_plafond_de_contributions_sources(monkeypatch):
    monkeypatch.setattr(author_grouping, "BATCH_SOURCE_CONTRIBUTIONS", 100)
    publications = [(1, 10), (2, 60), (3, 40), (4, 5), (5, 300), (6, 1)]
    assert publication_batches(publications) == [[1, 2, 3], [4, 5], [6]]


def test_un_lot_se_ferme_au_plafond_de_publications(monkeypatch):
    monkeypatch.setattr(author_grouping, "BATCH_SIZE", 2)
    assert publication_batches([(1, 1), (2, 1), (3, 1)]) == [[1, 2], [3]]


def test_seules_les_appartenances_changees_sont_reecrites():
    """1 inchangée ; 2 change de méthode ; 3 change de groupe ; 4 disparaît ; 5 apparaît."""
    stored = {
        1: MembershipRow(1, 10, 100, "name"),
        2: MembershipRow(2, 10, 200, "gap"),
        3: MembershipRow(3, 11, 100, "reference"),
        4: MembershipRow(4, 12, 200, "name"),
    }
    planned = [
        MembershipRow(1, 10, 100, "name"),
        MembershipRow(2, 10, 200, "name"),
        MembershipRow(3, 12, 100, "reference"),
        MembershipRow(5, 13, 300, "reference"),
    ]

    removed, inserted = membership_changes(stored, planned)

    assert sorted(removed) == [2, 3, 4, 5]
    assert [m.source_contribution for m in inserted] == [2, 3, 5]
