"""Lecture d'une valeur JSON : ce que chaque accesseur accepte, et ce qu'il écarte.

Une donnée reçue de l'extérieur n'a pas la forme annoncée mais celle qu'elle a. Ces tests fixent la frontière : ce qui est reconnu, ce qui vaut « absent », et les deux pièges que Python tend — le booléen qui est un entier, et la chaîne qui est une suite de caractères.
"""

import pytest

from domain.types import as_int, as_mapping, as_sequence, as_str


class TestAsStr:
    def test_chaine(self):
        assert as_str("un titre") == "un titre"

    def test_chaine_vide_conservee(self):
        """La chaîne vide est une valeur, que l'appelant traite comme il l'entend."""
        assert as_str("") == ""

    @pytest.mark.parametrize("valeur", [None, 2024, 3.5, True, ["un titre"], {"fr": "un titre"}])
    def test_ce_qui_n_est_pas_une_chaine(self, valeur):
        assert as_str(valeur) is None


class TestAsInt:
    def test_entier(self):
        assert as_int(2024) == 2024

    def test_zero_conserve(self):
        assert as_int(0) == 0

    def test_booleen_ecarte(self):
        """Python tient `True` pour l'entier 1 ; reçu là où un compte est attendu, il ne vaut rien."""
        assert as_int(True) is None
        assert as_int(False) is None

    @pytest.mark.parametrize("valeur", [None, "2024", 2024.5, [2024], {"annee": 2024}])
    def test_ce_qui_n_est_pas_un_entier(self, valeur):
        assert as_int(valeur) is None


class TestAsMapping:
    def test_objet(self):
        assert as_mapping({"cle": "valeur"}) == {"cle": "valeur"}

    @pytest.mark.parametrize("valeur", [None, "texte", 2024, 3.5, True, ["a"]])
    def test_ce_qui_n_est_pas_un_objet_rend_un_objet_vide(self, valeur):
        assert as_mapping(valeur) == {}

    def test_lecture_imbriquee_sans_verifier_chaque_niveau(self):
        """Le repli sur un objet vide permet d'enchaîner : une branche absente rend `None` au bout."""
        document = {"source": "pas un objet"}

        assert as_str(as_mapping(document.get("source")).get("titre")) is None


class TestAsSequence:
    def test_liste(self):
        assert as_sequence(["a", "b"]) == ["a", "b"]

    def test_liste_vide(self):
        assert as_sequence([]) == []

    def test_chaine_ecartee(self):
        """Python tient une chaîne pour une suite de caractères ; un champ JSON ne l'entend jamais ainsi."""
        assert as_sequence("abc") == []

    @pytest.mark.parametrize("valeur", [None, 2024, 3.5, True, {"cle": "valeur"}])
    def test_ce_qui_n_est_pas_une_liste(self, valeur):
        assert as_sequence(valeur) == []
