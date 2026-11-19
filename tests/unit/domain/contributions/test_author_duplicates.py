"""Doublons d'auteur dans la liste d'un enregistrement source (`domain.contributions.author_duplicates`)."""

from domain.contributions.author_duplicates import (
    cross_list_duplicates,
    duplicate_source_contributions,
    unaligned_duplicates,
)
from domain.contributions.author_grouping import SourceContribution, align_publication


def _source_record(names: list[str]) -> list[SourceContribution]:
    """Construit les contributions sources d'un enregistrement source, dans l'ordre : identifiant = position + 1, prénom = initiale du nom."""
    return [SourceContribution(i + 1, 1, i, name, name[0]) for i, name in enumerate(names)]


def _record(source_record: int, names: list[tuple[str, str]]) -> list[SourceContribution]:
    """Construit les contributions sources d'un enregistrement source, numérotées `source_record * 100 + position`, à partir de couples (nom de famille, prénom)."""
    return [
        SourceContribution(source_record * 100 + pos, source_record, pos, last, first)
        for pos, (last, first) in enumerate(names)
    ]


def _unaligned_duplicates(source_records: dict[int, list[SourceContribution]]) -> dict[int, int]:
    contributions = align_publication(source_records)
    by_id = {s.id: s for record in source_records.values() for s in record}
    return unaligned_duplicates(contributions, by_id)


class TestUnalignedDuplicates:
    def test_un_nom_repete_une_fois_reste_seul_et_devient_doublon(self):
        """HAL répète « delabaere / amelie » en tête de liste ; les autres sources l'ont une fois, en deuxième position."""
        hal = _record(
            1,
            [
                ("delabaere", "amelie"),
                ("leduc", "france"),
                ("delabaere", "amelie"),
                ("fuchs", "florent"),
            ],
        )
        openalex = _record(2, [("leduc", "france"), ("delabaere", "amelie"), ("fuchs", "florent")])
        assert _unaligned_duplicates({1: hal, 2: openalex}) == {100: 102}

    def test_des_homonymes_a_initiales_restent_deux_auteurs(self):
        wos = _record(1, [("martin", "a"), ("wang", "z"), ("wang", "z"), ("durand", "c")])
        crossref = _record(2, [("martin", "a"), ("wang", "zhen"), ("durand", "c")])
        assert _unaligned_duplicates({1: wos, 2: crossref}) == {}

    def test_des_homonymes_d_une_source_unique_restent_deux_auteurs(self):
        hal = _record(1, [("martin", "anne"), ("martin", "anne")])
        assert _unaligned_duplicates({1: hal}) == {}


def test_une_liste_recopiee_a_la_suite_vise_la_premiere_occurrence():
    duplicates = duplicate_source_contributions(
        _source_record(["martin", "petit", "durand", "martin", "petit", "durand"])
    )
    assert duplicates == {4: 1, 5: 2, 6: 3}


def test_une_recopie_partielle_suffit_avec_deux_noms_au_meme_decalage():
    duplicates = duplicate_source_contributions(
        _source_record(["martin", "petit", "durand", "leroy", "martin", "petit"])
    )
    assert duplicates == {5: 1, 6: 2}


def test_une_liste_recopiee_deux_fois_vise_la_premiere_occurrence():
    duplicates = duplicate_source_contributions(_source_record(["martin", "petit"] * 3))
    assert duplicates == {3: 1, 4: 2, 5: 1, 6: 2}


def test_des_homonymes_cote_a_cote_ne_sont_pas_des_doublons():
    """Liste alphabétique : deux paires d'homonymes, au décalage 1."""
    assert (
        duplicate_source_contributions(
            _source_record(["martin", "martin", "petit", "wang", "wang"])
        )
        == {}
    )


def test_un_seul_nom_repete_a_distance_n_est_pas_un_doublon():
    assert (
        duplicate_source_contributions(_source_record(["martin", "petit", "durand", "martin"]))
        == {}
    )


def test_une_liste_doublee_sur_place_donne_des_doublons():
    names = ["martin", "petit", "durand", "leroy"]
    duplicates = duplicate_source_contributions(
        _source_record([n for name in names for n in (name, name)])
    )
    assert duplicates == {2: 1, 4: 3, 6: 5, 8: 7}


def test_trois_paires_cote_a_cote_restent_des_homonymes():
    names = ["martin", "petit", "durand"]
    assert (
        duplicate_source_contributions(_source_record([n for name in names for n in (name, name)]))
        == {}
    )


def test_un_meme_nom_repete_quatre_fois_n_est_pas_une_liste_doublee():
    assert duplicate_source_contributions(_source_record(["wang"] * 8)) == {}


def test_une_liste_de_membres_reprenant_les_auteurs_dans_un_autre_ordre_donne_des_doublons():
    """Auteurs, puis membres du collectif : trois auteurs repris, chacun à son propre décalage."""
    authors = ["martin", "petit", "durand", "leroy", "moreau", "simon", "laurent", "michel"]
    members = ["durand", "garcia", "martin", "roux", "petit", "fournier"]
    duplicates = duplicate_source_contributions(_source_record(authors + members))
    assert duplicates == {9: 3, 11: 1, 13: 2}


def test_des_noms_repetes_a_distance_sous_le_seuil_restent_des_homonymes():
    """Deux noms répétés à distance, à des décalages différents, sur une liste de quarante noms."""
    names = [f"nom{i}" for i in range(38)]
    names[20:20] = ["nom3"]
    names[30:30] = ["nom7"]
    assert duplicate_source_contributions(_source_record(names)) == {}


class TestCrossListDuplicates:
    def test_un_nom_repete_sous_deux_graphies_et_cite_une_fois_ailleurs_est_un_doublon(self):
        """INSPIRE liste « porteboeuf / sarah julie » puis « porteboeuf houssais / s » ; HAL le cite une fois, en dernier. L'occurrence au rang de HAL est gardée."""
        inspire = _record(
            1, [("leroy", "anne"), ("porteboeuf", "sarah julie"), ("porteboeuf houssais", "s")]
        )
        hal = _record(2, [("leroy", "anne"), ("porteboeuf houssais", "s")])

        assert cross_list_duplicates({1: inspire, 2: hal}, references={1, 2}) == {101: 102}

    def test_l_occurrence_au_rang_des_autres_listes_est_gardee(self):
        """HAL répète « delabaere / amelie » en tête ; OpenAlex le cite une fois, en dernier."""
        hal = _record(1, [("delabaere", "amelie"), ("leduc", "france"), ("delabaere", "amelie")])
        openalex = _record(2, [("leduc", "france"), ("delabaere", "amelie")])

        assert cross_list_duplicates({1: hal, 2: openalex}, references={1, 2}) == {100: 102}

    def test_une_liste_hors_des_listes_de_reference_ne_compte_pas(self):
        inspire = _record(1, [("leroy", "anne"), ("porteboeuf", "s"), ("porteboeuf houssais", "s")])
        scanr = _record(2, [("porteboeuf houssais", "s")])

        assert cross_list_duplicates({1: inspire, 2: scanr}, references={1}) == {}

    def test_des_initiales_face_au_prenom_complet_signalent_deux_listes_bout_a_bout(self):
        """Toutes les sources ajoutent la liste des membres, aux initiales, après les auteurs."""
        authors = [("llorca", "pierre michel"), ("martin", "anne")]
        members = [("durand", "p"), ("llorca", "p m")]
        records = {n: _record(n, authors + members) for n in (1, 2)}

        assert cross_list_duplicates(records, references={1, 2}) == {103: 100, 203: 200}

    def test_un_nom_complet_repete_dans_une_courte_liste_est_un_doublon(self):
        records = {n: _record(n, [("godi", "patricia"), ("godi", "patricia")]) for n in (1, 2)}

        assert cross_list_duplicates(records, references={1, 2}) == {101: 100, 201: 200}

    def test_un_nom_complet_repete_dans_une_grande_collaboration_reste_des_homonymes(self):
        names = [(f"nom{i}", "jean") for i in range(120)] + [("hou", "yingrui"), ("hou", "yingrui")]
        records = {n: _record(n, names) for n in (10, 20)}

        assert cross_list_duplicates(records, references={10, 20}) == {}

    def test_un_nom_de_famille_prolonge_dans_une_grande_collaboration_est_un_doublon(self):
        others = [(f"nom{i}", "jean") for i in range(120)]
        inspire = _record(
            10, [*others, ("porteboeuf", "sarah julie"), ("porteboeuf houssais", "s")]
        )
        hal = _record(20, [*others, ("porteboeuf houssais", "s")])

        assert cross_list_duplicates({10: inspire, 20: hal}, references={10, 20}) == {1120: 1121}

    def test_des_initiales_proches_dans_une_grande_collaboration_restent_des_homonymes(self):
        """« wang / y » et « wang / y w » chez Crossref : une autre liste qui cite le nom une fois ne suffit pas."""
        others = [(f"nom{i}", "jean") for i in range(120)]
        crossref = _record(10, [*others, ("wang", "y"), ("wang", "y w")])
        hal = _record(20, [*others, ("wang", "y")])

        assert cross_list_duplicates({10: crossref, 20: hal}, references={10, 20}) == {}

    def test_deux_prenoms_differents_de_meme_initiale_sont_deux_auteurs(self):
        hal = _record(1, [("li", "yanru"), ("li", "yujie")])
        crossref = _record(2, [("li", "yanru")])

        assert cross_list_duplicates({1: hal, 2: crossref}, references={1, 2}) == {}

    def test_des_homonymes_presents_dans_toutes_les_listes_restent_distincts(self):
        records = {n: _record(n, [("xu", "z"), ("xu", "z"), ("martin", "anne")]) for n in (1, 2)}

        assert cross_list_duplicates(records, references={1, 2}) == {}

    def test_deux_orcid_differents_dans_une_autre_liste_designent_deux_homonymes(self):
        """Crossref liste deux « schmidt / j » sans ORCID ; HAL leur donne deux ORCID différents."""
        crossref = _record(1, [("schmidt", "j"), ("martin", "anne"), ("schmidt", "j")])
        hal = [
            SourceContribution(200, 2, 0, "schmidt", "j", "0000-0003-3424-337X"),
            SourceContribution(201, 2, 1, "martin", "anne"),
            SourceContribution(202, 2, 2, "schmidt", "j", "0000-0003-4027-7875"),
        ]
        scanr = _record(3, [("schmidt", "j"), ("martin", "anne")])

        assert cross_list_duplicates({1: crossref, 2: hal, 3: scanr}, references={1, 2, 3}) == {}

    def test_deux_orcid_differents_designent_deux_homonymes(self):
        doubled = [
            SourceContribution(100, 1, 0, "schmidt", "j", "0000-0003-3424-337X"),
            SourceContribution(101, 1, 1, "schmidt", "j", "0000-0003-4027-7875"),
        ]
        once = _record(2, [("schmidt", "j")])

        assert cross_list_duplicates({1: doubled, 2: once}, references={1, 2}) == {}
