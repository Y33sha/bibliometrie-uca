"""Copies dans la liste d'auteurs d'un enregistrement source."""

from domain.publications.author_grouping import SourceContribution
from domain.publications.list_copies import copied_source_contributions


def _source_record(names: list[str]) -> list[SourceContribution]:
    """Contributions sources d'un enregistrement source, dans l'ordre : identifiant = position + 1, prénom = initiale du nom."""
    return [SourceContribution(i + 1, 1, i, name, name[0]) for i, name in enumerate(names)]


def test_une_liste_recopiee_a_la_suite_vise_la_premiere_occurrence():
    copies = copied_source_contributions(
        _source_record(["martin", "petit", "durand", "martin", "petit", "durand"])
    )
    assert copies == {4: 1, 5: 2, 6: 3}


def test_une_copie_partielle_suffit_avec_deux_noms_au_meme_decalage():
    copies = copied_source_contributions(
        _source_record(["martin", "petit", "durand", "leroy", "martin", "petit"])
    )
    assert copies == {5: 1, 6: 2}


def test_une_liste_recopiee_deux_fois_vise_la_premiere_occurrence():
    copies = copied_source_contributions(_source_record(["martin", "petit"] * 3))
    assert copies == {3: 1, 4: 2, 5: 1, 6: 2}


def test_des_homonymes_cote_a_cote_ne_sont_pas_des_copies():
    """Liste alphabétique : deux paires d'homonymes, au décalage 1."""
    assert (
        copied_source_contributions(_source_record(["martin", "martin", "petit", "wang", "wang"]))
        == {}
    )


def test_un_seul_nom_repete_a_distance_n_est_pas_une_copie():
    assert (
        copied_source_contributions(_source_record(["martin", "petit", "durand", "martin"])) == {}
    )


def test_une_liste_doublee_sur_place_est_une_copie():
    names = ["martin", "petit", "durand", "leroy"]
    copies = copied_source_contributions(
        _source_record([n for name in names for n in (name, name)])
    )
    assert copies == {2: 1, 4: 3, 6: 5, 8: 7}


def test_trois_paires_cote_a_cote_restent_des_homonymes():
    names = ["martin", "petit", "durand"]
    assert (
        copied_source_contributions(_source_record([n for name in names for n in (name, name)]))
        == {}
    )


def test_un_meme_nom_repete_quatre_fois_n_est_pas_une_liste_doublee():
    assert copied_source_contributions(_source_record(["wang"] * 8)) == {}


def test_une_liste_de_membres_reprenant_les_auteurs_dans_un_autre_ordre_est_une_copie():
    """Auteurs, puis membres du collectif : trois auteurs repris, chacun à son propre décalage."""
    authors = ["martin", "petit", "durand", "leroy", "moreau", "simon", "laurent", "michel"]
    members = ["durand", "garcia", "martin", "roux", "petit", "fournier"]
    copies = copied_source_contributions(_source_record(authors + members))
    assert copies == {9: 3, 11: 1, 13: 2}


def test_des_noms_repetes_a_distance_sous_le_seuil_restent_des_homonymes():
    """Deux noms répétés à distance, à des décalages différents, sur une liste de quarante noms."""
    names = [f"nom{i}" for i in range(38)]
    names[20:20] = ["nom3"]
    names[30:30] = ["nom7"]
    assert copied_source_contributions(_source_record(names)) == {}
