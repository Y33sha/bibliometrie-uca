"""Similarité de deux noms d'auteur pour l'alignement."""

import pytest

from domain.contributions.name_similarity import (
    SIMILARITY_THRESHOLD,
    jaro_winkler,
    name_similarity,
)


def _score(a: tuple[str, str], b: tuple[str, str], *, unordered: bool = False) -> float:
    return name_similarity(*a, *b, unordered=unordered)[0]


class TestNameSimilarity:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            (
                ("da rocha puleoto", "carmella fernandes"),
                ("fernandes da rocha", "carmella puleoto"),
            ),
            (("navarro", "j e garcia"), ("garcia navarro", "jose enrique")),
            (("porteboeuf", "sarah julie"), ("porteboeuf houssais", "s")),
            (("guenther", "angela"), ("gunther", "angela")),
            (("vanhulse", "c b"), ("van hulse", "c b")),
            (("liu", "yanlin"), ("liu", "y l")),
        ],
        ids=[
            "découpage différent",
            "initiales et prénom complet",
            "nom de famille inclus",
            "voyelle infléchie",
            "mots collés",
            "initiales en surnombre",
        ],
    )
    def test_meme_auteur(self, a, b):
        assert _score(a, b) == 1.0

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            (("skaf", "ali"), ("alkire", "s p")),
            (("saoucha", "k a"), ("kugel", "a")),
            (("liu", "y l"), ("liu", "y w")),
            (("balaji", "s"), ("balakrishnan", "v")),
        ],
        ids=["mots courts proches", "initiales seules", "initiales contraires", "noms proches"],
    )
    def test_auteurs_differents(self, a, b):
        assert _score(a, b) <= SIMILARITY_THRESHOLD

    def test_hors_de_l_ordre_un_mot_identique_est_exige(self):
        a, b = ("beminghoff", "d"), ("berninghoff", "daniel")
        assert _score(a, b) == 1.0
        assert _score(a, b, unordered=True) == 0.0

    def test_des_mots_tries_tres_semblables_designent_le_meme_auteur(self):
        """Faute de frappe sur un mot court : la similarité des mots triés suffit, sauf hors de l'ordre."""
        a, b = ("thueer", "susann"), ("thuer", "susann")
        assert _score(a, b) == 1.0
        assert _score(a, b, unordered=True) <= SIMILARITY_THRESHOLD

    def test_deux_noms_vides_restent_distincts(self):
        assert _score(("", ""), ("", "")) == 0.0

    def test_les_mots_tries_departagent(self):
        """« dupont / jean » a le score maximal face à « dupont / jean » comme face à « dupont / j » ; la similarité des mots triés préfère le nom identique."""
        same = name_similarity("dupont", "jean", "dupont", "jean")
        initial = name_similarity("dupont", "jean", "dupont", "j")
        assert same[0] == initial[0]
        assert same[1] > initial[1]


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
    def test_valeurs(self, a, b, expected):
        """Les demi-transpositions s'arrondissent à l'entier inférieur."""
        assert jaro_winkler(a, b) == pytest.approx(expected)
