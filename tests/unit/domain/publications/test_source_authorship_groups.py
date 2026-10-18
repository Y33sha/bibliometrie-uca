"""Décisions pures des groupes de signatures."""

import math

import pytest

from domain.publications.source_authorship_groups import (
    Author,
    ResidualModel,
    comparison_levels,
    full_first_name,
    gap,
    jaro_winkler,
    link_threshold,
    longest_ordered,
    plan_group_ids,
)


def _author(last="dupont", first="jean", orcid="", idref="", gap=0):
    return Author(last_name=last, first_name=first, orcid=orcid, idref=idref, gap=gap)


class TestFullFirstName:
    def test_un_prenom_en_initiales_est_vide(self):
        assert full_first_name("j a") == ""

    def test_un_prenom_complet_reste(self):
        assert full_first_name("jean a") == "jean a"


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
