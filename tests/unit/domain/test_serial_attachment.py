"""Règles de rattachement d'un enregistrement source à sa revue (`domain.serials.attachment`)."""

from collections import Counter

from domain.serials.attachment import (
    TitledSerial,
    choose_issnl,
    effective_issnl,
    match_by_title,
    most_frequent,
    openalex_issnls,
)


def test_issn_l_du_sudoc_puis_d_openalex_puis_l_issn_lui_meme():
    openalex = {"1476-4687": "0028-0836"}
    assert effective_issnl("1476-4687", "0028-0836", {}) == "0028-0836"
    assert effective_issnl("1476-4687", None, openalex) == "0028-0836"
    assert effective_issnl("1476-4687", None, {}) == "1476-4687"


def test_issn_l_d_openalex_le_plus_frequent():
    issnls = openalex_issnls(
        [
            ("0028-0836", ("1476-4687",)),
            ("0028-0836", ("1476-4687",)),
            ("9999-9999", ("1476-4687",)),
        ]
    )
    assert issnls == {"0028-0836": "0028-0836", "1476-4687": "0028-0836", "9999-9999": "9999-9999"}


def test_valeur_la_plus_frequente_puis_la_plus_petite():
    assert most_frequent(Counter({"b": 2, "a": 2, "c": 1})) == "a"


def test_un_seul_issn_l_l_emporte_d_office():
    assert choose_issnl(None, {"0028-0836": "Nature"}) == "0028-0836"


def test_plusieurs_issn_l_departages_par_le_titre():
    """Cas réel : un article donne l'ISSN de « BMC Family Practice » et celui de son titre suivant."""
    candidates = {"1471-2296": "BMC family practice", "2731-4553": "BMC primary care"}
    assert choose_issnl("BMC Family Practice", candidates) == "1471-2296"
    assert choose_issnl("Autre titre", candidates) is None
    assert choose_issnl(None, candidates) is None


def test_rattachement_par_titre_a_la_seule_revue_d_editeur_compatible():
    serials = [TitledSerial(1, 10), TitledSerial(2, 20)]
    assert match_by_title(10, serials) == 1
    assert match_by_title(None, serials) is None
    assert match_by_title(30, [TitledSerial(3, None)]) == 3
    assert match_by_title(30, serials) is None
