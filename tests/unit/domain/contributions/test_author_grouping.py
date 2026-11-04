"""Décisions pures de l'alignement des auteurs."""

import pytest

from domain.contributions.author_grouping import (
    GroupingMethod,
    SourceContribution,
    align_publication,
    plan_contribution_ids,
    with_known_first_name,
)


def _source_record(source_record, names, start=0):
    """Construit les contributions sources d'un enregistrement source, numérotées `source_record * 100 + position`, à partir de couples (nom de famille, prénom)."""
    return [
        SourceContribution(source_record * 100 + pos, source_record, pos, last, first)
        for pos, (last, first) in enumerate(names, start)
    ]


def _aligned(contributions):
    """Renvoie les contributions sources de chaque contribution qui en a plusieurs, avec la méthode de chacune."""
    return sorted(
        sorted((m.source_contribution, m.method) for m in g.members)
        for g in contributions
        if len(g.members) > 1
    )


def _pair(reference, other, method):
    return [(reference, GroupingMethod.REFERENCE), (other, method)]


class TestAlignPublication:
    def test_noms_uniques_lies_a_la_liste_la_plus_longue(self):
        source_records = {
            1: _source_record(1, [("martin", "a"), ("petit", "b"), ("durand", "c")]),
            2: _source_record(2, [("martin", "a"), ("durand", "c")]),
        }
        assert _aligned(align_publication(source_records)) == [
            _pair(100, 200, GroupingMethod.NAME),
            _pair(102, 201, GroupingMethod.NAME),
        ]

    def test_un_nom_decoupe_autrement_se_lie_dans_son_trou(self):
        """Même autrice, nom de famille et prénom découpés autrement : seule dans son trou, elle se lie par la ressemblance des noms complets."""
        reference = [("fernandes da rocha", "carmella puleoto"), ("tessier", "nicolas")]
        other = [("da rocha puleoto", "carmella fernandes"), ("tessier", "nicolas")]
        contributions = align_publication(
            {1: _source_record(1, reference), 2: _source_record(2, other)}
        )
        assert _pair(100, 200, GroupingMethod.GAP) in _aligned(contributions)

    def test_homonymes_lies_dans_l_ordre_de_leur_trou(self):
        names = [("martin", "a"), ("zhang", "y"), ("zhang", "y"), ("durand", "c")]
        contributions = align_publication(
            {1: _source_record(1, names), 2: _source_record(2, names)}
        )
        assert _pair(101, 201, GroupingMethod.GAP) in _aligned(contributions)
        assert _pair(102, 202, GroupingMethod.GAP) in _aligned(contributions)

    def test_un_trou_inegal_lie_le_nom_le_plus_semblable(self):
        reference = [("martin", "a"), ("pelegris", "i"), ("pena martinez", "s"), ("durand", "c")]
        other = [("martin", "a"), ("martinez", "s pena"), ("durand", "c")]
        contributions = align_publication(
            {1: _source_record(1, reference), 2: _source_record(2, other)}
        )
        assert _pair(102, 201, GroupingMethod.GAP) in _aligned(contributions)

    def test_un_nom_hors_de_son_trou_se_lie_sans_ordre(self):
        """La liste suit un autre ordre : « dores cruz » tombe dans un autre trou, et se lie dans le résidu sans ordre."""
        reference = [
            ("martin", "a"),
            ("dores cruz", "terence daniel"),
            ("petit", "b"),
            ("durand", "c"),
        ]
        other = [("martin", "a"), ("petit", "b"), ("durand", "c"), ("cruz", "terence daniel dores")]
        contributions = align_publication(
            {1: _source_record(1, reference), 2: _source_record(2, other)}
        )
        assert _pair(101, 203, GroupingMethod.UNORDERED) in _aligned(contributions)

    def test_hors_de_l_ordre_un_mot_identique_est_exige(self):
        """« strebler / thomas » et « thompson / a s » se ressemblent par des mots proches seulement : hors de leur trou, ils restent distincts."""
        reference = [("martin", "a"), ("thompson", "a s"), ("durand", "c")]
        other = [("martin", "a"), ("durand", "c"), ("strebler", "thomas")]
        contributions = align_publication(
            {1: _source_record(1, reference), 2: _source_record(2, other)}
        )
        assert _aligned(contributions) == [
            _pair(100, 200, GroupingMethod.NAME),
            _pair(102, 201, GroupingMethod.NAME),
        ]

    def test_la_position_seule_ne_lie_pas(self):
        """Deux listes sans aucun nom commun : le même trou ne suffit pas à lier deux auteurs."""
        contributions = align_publication(
            {
                1: _source_record(1, [("martin", "anne"), ("petit", "bruno")]),
                2: _source_record(2, [("durand", "claire"), ("leroy", "denis")]),
            }
        )
        assert _aligned(contributions) == []

    def test_des_noms_proches_aux_initiales_contraires_ne_se_lient_pas(self):
        """« V. Balakrishnan » occupe la place de « S. Balaji » entre deux auteurs liés."""
        reference = _source_record(1, [("martin", "a"), ("balaji", "s"), ("durand", "c")])
        other = _source_record(2, [("martin", "a"), ("balakrishnan", "v"), ("durand", "c")])
        contributions = align_publication({1: reference, 2: other})
        assert all(
            len(g.members) == 1 for g in contributions if g.reference.last_name.startswith("bala")
        )

    def test_un_nom_de_famille_sans_prenom_se_lie_dans_son_trou(self):
        """Deux « Martin » de chaque côté : le prénom complet lie Anne, puis le Martin sans prénom rejoint le seul « Martin » de son trou."""
        reference = _source_record(1, [("martin", "anne"), ("martin", "bruno"), ("petit", "c")])
        other = _source_record(2, [("martin", "anne"), ("martin", "")])
        assert _aligned(align_publication({1: reference, 2: other})) == [
            _pair(100, 200, GroupingMethod.NAME),
            _pair(101, 201, GroupingMethod.GAP),
        ]

    def test_une_contribution_fondee_par_une_liste_plus_courte_suit_sa_voisine_precedente(self):
        """« Giromini » manque à la liste la plus longue : sa contribution se range après « Durand », son voisin précédent. Sa position brute le rangerait après « Roux »."""
        longest = _source_record(
            1, [("martin", "a"), ("petit", "b"), ("durand", "c"), ("leroy", "d"), ("roux", "e")]
        )
        shorter = _source_record(
            2,
            [("martin", "a"), ("petit", "b"), ("durand", "c"), ("giromini", "p"), ("leroy", "d")],
            start=1,
        )
        contributions = align_publication({1: longest, 2: shorter})
        assert [g.reference.last_name for g in contributions] == [
            "martin",
            "petit",
            "durand",
            "giromini",
            "leroy",
            "roux",
        ]

    def test_une_contribution_source_sans_position_se_lie_par_le_nom_hors_de_l_ordre(self):
        """Jury d'une thèse chez theses.fr, sans position : il se lie par le nom au jury positionné d'un autre enregistrement source, quel que soit son rang."""
        reference = _source_record(1, [("martin", "a"), ("petit", "b"), ("durand", "c")])
        unordered = [
            SourceContribution(200, 2, 0, "martin", "anne"),
            SourceContribution(201, 2, None, "durand", "claire"),
            SourceContribution(202, 2, None, "petit", "bruno"),
        ]
        assert _aligned(align_publication({1: reference, 2: unordered})) == [
            _pair(100, 200, GroupingMethod.NAME),
            _pair(101, 202, GroupingMethod.NAME),
            _pair(102, 201, GroupingMethod.NAME),
        ]

    def test_un_jury_sans_position_au_nom_decoupe_autrement_se_lie_sans_ordre(self):
        theses = [
            SourceContribution(100, 1, None, "labra gayo", "jose emilio"),
            SourceContribution(101, 1, None, "martin", "anne"),
        ]
        scanr = [
            SourceContribution(200, 2, None, "gayo", "jose emilio labra"),
            SourceContribution(201, 2, None, "martin", "anne"),
        ]
        assert _pair(100, 200, GroupingMethod.UNORDERED) in _aligned(
            align_publication({1: theses, 2: scanr})
        )

    def test_un_enregistrement_source_qui_intervertit_nom_et_prenom_s_aligne(self):
        """Un enregistrement source donne le prénom à la place du nom de famille pour tous ses auteurs : chacun se lie par le nom à son auteur de la référence."""
        reference = [("piaton", "sophie"), ("roger leroi", "valerie"), ("vallet", "guillaume t")]
        inverted = [("sophie", "piaton"), ("valerie", "roger leroi"), ("guillaume", "vallet")]
        contributions = align_publication(
            {1: _source_record(1, reference), 2: _source_record(2, inverted)}
        )
        assert _aligned(contributions) == [
            _pair(100 + pos, 200 + pos, GroupingMethod.NAME) for pos in range(3)
        ]

    def test_un_auteur_interverti_se_lie_dans_son_trou(self):
        """Le deuxième enregistrement source intervertit un auteur aux prénoms complets : il se lie par la ressemblance des noms complets."""
        authors = [("martin", "anne"), ("gocko", "xavier"), ("durand", "claire")]
        swapped = [("martin", "anne"), ("xavier", "gocko"), ("durand", "claire")]
        contributions = align_publication(
            {1: _source_record(1, authors), 2: _source_record(2, swapped)}
        )
        assert _pair(101, 201, GroupingMethod.GAP) in _aligned(contributions)

    def test_a_longueur_egale_un_enregistrement_source_reporte_ne_fonde_pas_les_contributions(self):
        first = _source_record(1, [("hollandts", "xavier"), ("hollandts", "xavier")])
        second = _source_record(2, [("valiorgue", "bertrand"), ("hollandts", "xavier")])
        contributions = align_publication({1: first, 2: second}, deferred={1})
        assert {g.reference.id for g in contributions} >= {200, 201}

    def test_au_maximum_une_contribution_source_par_enregistrement_source(self):
        names = [("zhang", "y"), ("zhang", "y"), ("zhang", "y")]
        source_records = {
            1: _source_record(1, names),
            2: _source_record(2, names[:2]),
            3: _source_record(3, names[:1]),
        }
        for contribution in align_publication(source_records):
            source_records_of_contribution = [m.source_record for m in contribution.members]
            assert len(source_records_of_contribution) == len(set(source_records_of_contribution))


class TestWithKnownFirstName:
    @pytest.mark.parametrize(
        "first_name, known, expected",
        [
            ("z", "zhihao", "zhihao"),
            ("", "zhihao", "zhihao"),
            ("j a", "jean andre", "jean andre"),
            ("y", "zhihao", "y"),
            ("zehua", "zhihao", "zehua"),
            ("z", "", "z"),
            ("z", "z", "z"),
        ],
        ids=[
            "initiale",
            "absent",
            "initiales",
            "incompatible",
            "complet",
            "inconnu",
            "connu en initiale",
        ],
    )
    def test_prenom_pour_l_alignement(self, first_name, known, expected):
        assert with_known_first_name(first_name, known) == expected


class TestPlanContributionIds:
    def test_contributions_inchangees_gardent_leur_identifiant(self):
        old = {7: frozenset({1, 2}), 9: frozenset({3})}
        assert plan_contribution_ids(old, [frozenset({3}), frozenset({1, 2})]) == [9, 7]

    def test_le_plus_grand_recouvrement_reprend_l_identifiant(self):
        old = {7: frozenset({1, 2, 3})}
        assert plan_contribution_ids(old, [frozenset({1}), frozenset({2, 3, 4})]) == [None, 7]

    def test_egalite_le_plus_petit_identifiant(self):
        old = {7: frozenset({1}), 5: frozenset({2})}
        assert plan_contribution_ids(old, [frozenset({1, 2})]) == [5]

    def test_contribution_sans_ancienne_correspondante(self):
        assert plan_contribution_ids({}, [frozenset({1})]) == [None]
