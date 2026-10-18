"""Copies dans la liste d'auteurs d'une notice."""

from domain.publications.author_grouping import Signature
from domain.publications.list_copies import copied_signatures


def _notice(names: list[str]) -> list[Signature]:
    """Signatures d'une notice, dans l'ordre : identifiant = position + 1, prénom = initiale du nom."""
    return [Signature(i + 1, 1, i, name, name[0]) for i, name in enumerate(names)]


def test_une_liste_recopiee_a_la_suite_vise_la_premiere_occurrence():
    copies = copied_signatures(_notice(["martin", "petit", "durand", "martin", "petit", "durand"]))
    assert copies == {4: 1, 5: 2, 6: 3}


def test_une_copie_partielle_suffit_avec_deux_noms_au_meme_decalage():
    copies = copied_signatures(_notice(["martin", "petit", "durand", "leroy", "martin", "petit"]))
    assert copies == {5: 1, 6: 2}


def test_une_liste_recopiee_deux_fois_vise_la_premiere_occurrence():
    copies = copied_signatures(_notice(["martin", "petit"] * 3))
    assert copies == {3: 1, 4: 2, 5: 1, 6: 2}


def test_des_homonymes_cote_a_cote_ne_sont_pas_des_copies():
    """Liste alphabétique : deux paires d'homonymes, au décalage 1."""
    assert copied_signatures(_notice(["martin", "martin", "petit", "wang", "wang"])) == {}


def test_un_seul_nom_repete_a_distance_n_est_pas_une_copie():
    assert copied_signatures(_notice(["martin", "petit", "durand", "martin"])) == {}


def test_une_liste_doublee_sur_place_est_une_copie():
    names = ["martin", "petit", "durand", "leroy"]
    copies = copied_signatures(_notice([n for name in names for n in (name, name)]))
    assert copies == {2: 1, 4: 3, 6: 5, 8: 7}


def test_trois_paires_cote_a_cote_restent_des_homonymes():
    names = ["martin", "petit", "durand"]
    assert copied_signatures(_notice([n for name in names for n in (name, name)])) == {}


def test_un_meme_nom_repete_quatre_fois_n_est_pas_une_liste_doublee():
    assert copied_signatures(_notice(["wang"] * 8)) == {}
