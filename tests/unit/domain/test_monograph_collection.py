"""Tests de l'entrée de `serials` d'une monographie (`domain.monographs.collection`)."""

from domain.monographs.collection import MonographSerialChoice, choose_monograph_serial


def test_collection_a_issn_avant_le_volume():
    assert choose_monograph_serial((7,), (99,)) == MonographSerialChoice(7)


def test_a_defaut_le_volume():
    assert choose_monograph_serial((), (99,)) == MonographSerialChoice(99)


def test_sans_entree_aucune():
    """Sans collection ni volume, aucune revue n'est choisie."""
    assert choose_monograph_serial((), ()) == MonographSerialChoice(None)


def test_plusieurs_collections_en_conflit():
    assert choose_monograph_serial((4, 5), ()) == MonographSerialChoice(None, (4, 5))


def test_plusieurs_volumes_en_conflit():
    assert choose_monograph_serial((), (8, 9)) == MonographSerialChoice(None, (8, 9))


def test_serie_sans_issn_avant_le_volume():
    assert choose_monograph_serial((), (99,), series_id=500) == MonographSerialChoice(500)


def test_collection_a_issn_avant_la_serie_sans_issn():
    assert choose_monograph_serial((7,), (), series_id=500) == MonographSerialChoice(7)
