"""Tests de l'entrée de `journals` d'une monographie (`domain.monographs.collection`)."""

from domain.monographs.collection import MonographJournalChoice, choose_monograph_journal


def test_collection_a_issn_avant_le_volume():
    assert choose_monograph_journal((7,), (99,)) == MonographJournalChoice(7)


def test_a_defaut_le_volume():
    assert choose_monograph_journal((), (99,)) == MonographJournalChoice(99)


def test_sans_entree_aucune():
    """Régression : un chapitre détaché de la revue que lui prêtait l'espace de noms de son DOI laissait la revue à sa monographie."""
    assert choose_monograph_journal((), ()) == MonographJournalChoice(None)


def test_plusieurs_collections_en_conflit():
    assert choose_monograph_journal((4, 5), ()) == MonographJournalChoice(None, (4, 5))


def test_plusieurs_volumes_en_conflit():
    assert choose_monograph_journal((), (8, 9)) == MonographJournalChoice(None, (8, 9))


def test_serie_sans_issn_avant_le_volume():
    assert choose_monograph_journal((), (99,), series_id=500) == MonographJournalChoice(500)


def test_collection_a_issn_avant_la_serie_sans_issn():
    assert choose_monograph_journal((7,), (), series_id=500) == MonographJournalChoice(7)
