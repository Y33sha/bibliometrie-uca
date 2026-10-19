"""Décisions pures des groupes de signatures."""

import math

import pytest

from domain.publications.author_grouping import (
    Author,
    GroupingMethod,
    ResidualModel,
    Signature,
    align_publication,
    comparison_levels,
    full_first_name,
    gap,
    jaro_winkler,
    link_threshold,
    longest_ordered,
    plan_group_ids,
    position_only,
    with_known_first_name,
)
from pipeline.transformation.publications.author_grouping.residual_weights import (
    RESIDUAL_WEIGHTS,
)


def _author(last="dupont", first="jean", orcid="", idref="", gap=0):
    return Author(last_name=last, first_name=first, orcid=orcid, idref=idref, gap=gap)


def _notice(notice, names, start=0):
    """Signatures d'une notice, numérotées `notice * 100 + position`, à partir de couples (patronyme, prénom)."""
    return [
        Signature(notice * 100 + pos, notice, pos, last, first)
        for pos, (last, first) in enumerate(names, start)
    ]


def _greedy(matrix):
    """Affectation gloutonne, suffisante pour des matrices sans conflit."""
    taken_rows, taken_cols, out = set(), set(), []
    cells = sorted(
        ((v, i, j) for i, row in enumerate(matrix) for j, v in enumerate(row)), reverse=True
    )
    for _, i, j in cells:
        if i not in taken_rows and j not in taken_cols:
            taken_rows.add(i)
            taken_cols.add(j)
            out.append((i, j))
    return out


def _grouped(groups):
    """Signatures de chaque groupe de plus d'une signature, avec la méthode de chaque membre."""
    return sorted(
        sorted((m.signature, m.method) for m in g.members) for g in groups if len(g.members) > 1
    )


class TestAlignPublication:
    def test_noms_uniques_lies_a_la_liste_la_plus_longue(self):
        notices = {
            1: _notice(1, [("martin", "a"), ("petit", "b"), ("durand", "c")]),
            2: _notice(2, [("martin", "a"), ("durand", "c")]),
        }
        groups = align_publication(notices)
        assert _grouped(groups) == [
            [(100, GroupingMethod.REFERENCE), (200, GroupingMethod.NAME)],
            [(102, GroupingMethod.REFERENCE), (201, GroupingMethod.NAME)],
        ]

    def test_homonymes_lies_dans_l_ordre(self):
        names = [("martin", "a"), ("zhang", "y"), ("zhang", "y"), ("durand", "c")]
        groups = align_publication({1: _notice(1, names), 2: _notice(2, names)})
        assert [(101, GroupingMethod.REFERENCE), (201, GroupingMethod.ORDER)] in _grouped(groups)
        assert [(102, GroupingMethod.REFERENCE), (202, GroupingMethod.ORDER)] in _grouped(groups)

    def test_l_identifiant_d_un_membre_lie_au_groupe(self):
        """La référence est sans ORCID ; un membre venu de la deuxième notice a l'ORCID, et la troisième notice rejoint son groupe, même dans l'ordre inverse."""
        reference = _notice(1, [("martin", "anne"), ("martin", "bruno")])
        with_orcid = [
            Signature(200, 2, 0, "martin", "a", orcid="A"),
            Signature(201, 2, 1, "martin", "b", orcid="B"),
        ]
        without_name = [
            Signature(300, 3, 0, "martin", "", orcid="B"),
            Signature(301, 3, 1, "martin", "", orcid="A"),
        ]
        groups = align_publication({1: reference, 2: with_orcid, 3: without_name})
        assert _grouped(groups) == [
            [
                (100, GroupingMethod.REFERENCE),
                (200, GroupingMethod.NAME),
                (301, GroupingMethod.IDENTIFIER),
            ],
            [
                (101, GroupingMethod.REFERENCE),
                (201, GroupingMethod.NAME),
                (300, GroupingMethod.IDENTIFIER),
            ],
        ]

    def test_un_identifiant_present_dans_deux_groupes_ne_lie_rien(self):
        reference = _notice(1, [("martin", "anne"), ("martin", "bruno")])
        both = [
            Signature(200, 2, 0, "martin", "a", orcid="A"),
            Signature(201, 2, 1, "martin", "b", orcid="A"),
        ]
        groups = align_publication(
            {1: reference, 2: both, 3: [Signature(300, 3, 0, "martin", "", orcid="A")]}
        )
        assert all(
            300 not in {m.signature for m in g.members} or len(g.members) == 1 for g in groups
        )

    def test_un_lien_qui_croise_l_ordre_est_ecarte(self):
        """Patronyme unique à l'autre bout de la liste : sans filtre d'ordre, « Ferrer » serait lié à « Ferrer » malgré les auteurs liés entre eux."""
        reference = [("martin", "a"), ("petit", "b"), ("durand", "c"), ("ferrer", "j")]
        other = [("ferrer", "a"), ("martin", "a"), ("petit", "b"), ("durand", "c")]
        notices = {1: _notice(1, reference), 2: _notice(2, other)}
        assert [(103, GroupingMethod.REFERENCE), (200, GroupingMethod.NAME)] not in _grouped(
            align_publication(notices)
        )

    def test_une_signature_sans_position_se_lie_par_le_nom_hors_de_l_ordre(self):
        """Jury d'une thèse chez theses.fr, sans position : il se lie par le nom au jury positionné d'une autre notice, quel que soit son rang."""
        reference = _notice(1, [("martin", "a"), ("petit", "b"), ("durand", "c")])
        unordered = [
            Signature(200, 2, 0, "martin", "anne"),
            Signature(201, 2, None, "durand", "claire"),
            Signature(202, 2, None, "petit", "bruno"),
        ]
        groups = align_publication({1: reference, 2: unordered})
        assert sorted(_grouped(groups)) == [
            [(100, GroupingMethod.REFERENCE), (200, GroupingMethod.NAME)],
            [(101, GroupingMethod.REFERENCE), (202, GroupingMethod.NAME)],
            [(102, GroupingMethod.REFERENCE), (201, GroupingMethod.NAME)],
        ]

    def test_une_notice_qui_intervertit_nom_et_prenom_s_aligne_dans_l_ordre(self):
        """Les quatre autres sources donnent « Roger-Leroi Valerie » : le prénom tient la place du patronyme pour toute la notice."""
        reference = [("piaton", "sophie"), ("roger leroi", "valerie"), ("vallet", "guillaume t")]
        inverted = [("sophie", "piaton"), ("valerie", "roger leroi"), ("guillaume", "vallet")]
        groups = align_publication({1: _notice(1, reference), 2: _notice(2, inverted)})
        assert _grouped(groups) == [
            [(100, GroupingMethod.REFERENCE), (200, GroupingMethod.NAME)],
            [(101, GroupingMethod.REFERENCE), (201, GroupingMethod.NAME)],
            [(102, GroupingMethod.REFERENCE), (202, GroupingMethod.NAME)],
        ]

    def test_a_longueur_egale_une_notice_reportee_ne_fonde_pas_les_groupes(self):
        first = _notice(1, [("hollandts", "xavier"), ("hollandts", "xavier")])
        second = _notice(2, [("valiorgue", "bertrand"), ("hollandts", "xavier")])
        groups = align_publication({1: first, 2: second}, deferred={1})
        assert {g.reference.id for g in groups} >= {200, 201}

    def test_le_residu_de_la_regle_est_transmis_notice_par_notice(self):
        reference = [("martin", "a"), ("garcia navarro", "j e"), ("durand", "c")]
        other = [("martin", "a"), ("navarro", "j e garcia"), ("durand", "c")]
        received = []
        align_publication(
            {1: _notice(1, reference), 2: _notice(2, other)},
            on_residual=lambda notice, sigs, groups: received.append((notice, sigs, groups)),
        )
        assert received == [
            (
                2,
                [_author("navarro", "j e garcia", gap=1)],
                [_author("garcia navarro", "j e", gap=1)],
            )
        ]

    def test_le_residu_lie_une_variante_avec_score_et_marge(self):
        model = ResidualModel(
            weights={
                "ln": {"mots inclus": 9.0, "else": -3.0},
                "fn": {"initiales concordantes": 3.0, "else": -1.0},
                "orcid": {},
                "idref": {},
                "gap": {"même trou": 6.0, "trou voisin": 4.0, "ailleurs": -1.0},
            }
        )
        reference = [("martin", "a"), ("garcia navarro", "j e"), ("durand", "c")]
        other = [("martin", "a"), ("navarro", "j e garcia"), ("durand", "c")]
        groups = align_publication(
            {1: _notice(1, reference), 2: _notice(2, other)}, model=model, assign=_greedy
        )
        variant = next(g for g in groups if g.reference.id == 101)
        member = next(m for m in variant.members if m.signature == 201)
        assert member.method == GroupingMethod.MODEL
        assert member.score == pytest.approx(18.0)
        assert member.margin is not None and member.margin > 0

    def test_la_position_seule_ne_lie_pas(self):
        """Deux listes sans aucun nom commun : le même trou ne suffit pas à lier deux auteurs."""
        model = ResidualModel(RESIDUAL_WEIGHTS)
        groups = align_publication(
            {
                1: _notice(1, [("martin", "anne"), ("petit", "bruno")]),
                2: _notice(2, [("durand", "claire"), ("leroy", "denis")]),
            },
            model=model,
            assign=_greedy,
        )
        assert _grouped(groups) == []

    def test_un_identifiant_commun_lie_malgre_des_noms_sans_ressemblance(self):
        model = ResidualModel(RESIDUAL_WEIGHTS)
        orcid = "0000-0001-2345-6789"
        groups = align_publication(
            {
                1: [Signature(100, 1, 0, "martin", "anne", orcid)],
                2: [Signature(200, 2, 0, "dupont", "claire", orcid)],
            },
            model=model,
            assign=_greedy,
        )
        assert _grouped(groups) == [[(100, GroupingMethod.REFERENCE), (200, GroupingMethod.MODEL)]]

    def test_au_maximum_une_signature_par_notice(self):
        names = [("zhang", "y"), ("zhang", "y"), ("zhang", "y")]
        notices = {1: _notice(1, names), 2: _notice(2, names[:2]), 3: _notice(3, names[:1])}
        for group in align_publication(notices):
            notices_of_group = [m.notice for m in group.members]
            assert len(notices_of_group) == len(set(notices_of_group))


class TestPositionOnly:
    def test_noms_sans_ressemblance(self):
        assert position_only(_author("martin", "anne"), _author("durand", "claire"))

    def test_prenom_absent(self):
        assert position_only(_author("martin", ""), _author("durand", "claire"))

    def test_patronyme_proche(self):
        assert not position_only(_author("martin", "anne"), _author("martins", "claire"))

    def test_identifiant_commun(self):
        assert not position_only(
            _author("martin", "anne", orcid="0000"), _author("durand", "claire", orcid="0000")
        )


class TestFullFirstName:
    def test_un_prenom_en_initiales_est_vide(self):
        assert full_first_name("j a") == ""

    def test_un_prenom_complet_reste(self):
        assert full_first_name("jean a") == "jean a"


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


class TestLongestOrdered:
    def test_un_lien_qui_croise_les_autres_est_ecarte(self):
        """Patronyme unique lié à 1 800 positions d'écart : « A. Ferrer » en 757, « J. A. Valls Ferrer » en 2579."""
        links = [(10, 1, 1), (20, 2, 2), (757, 2579, 3), (800, 800, 4), (900, 900, 5)]
        assert longest_ordered(links) == {1, 2, 4, 5}

    def test_aucun_lien(self):
        assert longest_ordered([]) == set()


class TestGap:
    def test_nombre_d_ancres_qui_precedent(self):
        assert [gap([10, 20, 30], v) for v in (5, 15, 25, 35)] == [0, 1, 2, 3]


class TestJaroWinkler:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            ("capriles", "koehler", 0.4900793650793651),
            ("borsato", "barisits", 0.7417857142857143),
            ("dupont", "dupont", 1.0),
            ("", "dupont", 0.0),
        ],
    )
    def test_valeurs_de_duckdb(self, a, b, expected):
        """Régression : les demi-transpositions s'arrondissent à l'entier inférieur, comme dans DuckDB."""
        assert jaro_winkler(a, b) == pytest.approx(expected)


class TestComparisonLevels:
    def test_patronyme_inclus_et_initiales_concordantes(self):
        levels = comparison_levels(
            _author("garcia navarro", "j e"), _author("navarro", "j e garcia")
        )
        assert levels["ln"] == "mots inclus"
        assert levels["fn"] == "initiales concordantes"

    def test_valeurs_absentes_et_trous(self):
        levels = comparison_levels(_author(orcid="0000-0001", gap=3), _author(gap=4))
        assert levels["orcid"] is None
        assert levels["gap"] == "trou voisin"


class TestResidualModel:
    def test_score_somme_des_poids_des_niveaux_presents(self):
        model = ResidualModel(
            weights={
                "ln": {"Exact match on ln": 9.0},
                "fn": {"Exact match on fn": 4.0},
                "orcid": {"exact": 12.0},
                "idref": {},
                "gap": {"même trou": 6.0},
            }
        )
        assert model.score(_author(), _author()) == 19.0


def test_seuil_log2_du_nombre_de_groupes():
    assert link_threshold(8) == 3.0
    assert link_threshold(1) == 1.0
    assert link_threshold(1000) == pytest.approx(math.log2(1000))


class TestPlanGroupIds:
    def test_groupes_inchanges_gardent_leur_identifiant(self):
        old = {7: frozenset({1, 2}), 9: frozenset({3})}
        assert plan_group_ids(old, [frozenset({3}), frozenset({1, 2})]) == [9, 7]

    def test_le_plus_grand_recouvrement_reprend_l_identifiant(self):
        old = {7: frozenset({1, 2, 3})}
        assert plan_group_ids(old, [frozenset({1}), frozenset({2, 3, 4})]) == [None, 7]

    def test_egalite_le_plus_petit_identifiant(self):
        old = {7: frozenset({1}), 5: frozenset({2})}
        assert plan_group_ids(old, [frozenset({1, 2})]) == [5]

    def test_groupe_sans_ancien_correspondant(self):
        assert plan_group_ids({}, [frozenset({1})]) == [None]
