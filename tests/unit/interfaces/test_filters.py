"""Lecture des paramètres de requête à plusieurs valeurs séparées par des virgules.

Le découpage par virgules garde les URL lisibles, mais soustrait la liste à la validation de FastAPI. Ces fonctions refusent à sa place ce qu'elle aurait refusé, avec le même code (422).
"""

import pytest
from fastapi import HTTPException

from interfaces.api.filters import (
    parse_int_csv,
    parse_ints,
    parse_ror_csv,
    parse_str_csv,
    parse_vocabulary_csv,
)


class TestListeDEntiers:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("", []),
            ("2024", [2024]),
            ("2023,2024", [2023, 2024]),
            (" 2023 , 2024 ", [2023, 2024]),  # les espaces autour des valeurs sont tolérés
            ("2023,,2024", [2023, 2024]),  # les positions vides sont ignorées
        ],
    )
    def test_decoupe_les_entiers(self, brut, attendu):
        assert parse_int_csv(brut, param="year") == attendu

    @pytest.mark.parametrize("brut", ["abc", "2024,abc", "2024;2025", "1e3", "2 024"])
    def test_refuse_ce_qui_n_est_pas_un_entier(self, brut):
        """Une valeur non entière donne 422 ; sans ce contrôle, l'erreur de conversion donnerait 500."""
        with pytest.raises(HTTPException) as leve:
            parse_int_csv(brut, param="year")
        assert leve.value.status_code == 422

    def test_le_refus_nomme_le_parametre_et_les_valeurs_fautives(self):
        with pytest.raises(HTTPException) as leve:
            parse_int_csv("2024,abc,def", param="year")
        detail = leve.value.detail
        assert "year" in detail
        assert "abc" in detail
        assert "def" in detail
        assert "2024" not in detail

    def test_un_nombre_trop_long_pour_etre_lu_est_refuse_de_meme(self):
        """L'interpréteur borne la conversion d'un littéral décimal ; le dépassement reste une requête malformée."""
        with pytest.raises(HTTPException) as leve:
            parse_int_csv("9" * 5000, param="year")
        assert leve.value.status_code == 422


class TestListeDejaDecoupee:
    def test_convertit_les_valeurs_restantes(self):
        assert parse_ints(["12", "34"], param="lab_id") == [12, 34]

    def test_refuse_une_intruse(self):
        with pytest.raises(HTTPException) as leve:
            parse_ints(["12", "none"], param="lab_id")
        assert leve.value.status_code == 422


class TestListeDeChaines:
    def test_decoupe_et_deshabille_les_valeurs(self):
        assert parse_str_csv(" a , b ,, c ") == ["a", "b", "c"]

    def test_une_chaine_vide_ne_rend_rien(self):
        assert parse_str_csv("") == []


class TestVocabulaireFerme:
    def test_accepte_les_valeurs_du_vocabulaire(self):
        assert parse_vocabulary_csv("a,b", allowed={"a", "b", "c"}, param="doc_type") == ["a", "b"]

    def test_refuse_une_valeur_hors_vocabulaire(self):
        with pytest.raises(HTTPException) as leve:
            parse_vocabulary_csv("a,z", allowed={"a", "b"}, param="doc_type")
        assert leve.value.status_code == 422
        assert "z" in leve.value.detail


class TestListeDeRor:
    def test_forme_courte_depuis_une_url(self):
        assert parse_ror_csv("https://ror.org/01a8ajp46,03vgfxd91", param="p") == [
            "01a8ajp46",
            "03vgfxd91",
        ]

    def test_ror_invalide_refuse(self):
        with pytest.raises(HTTPException) as exc:
            parse_ror_csv("pas-un-ror", param="partner_ror")
        assert exc.value.status_code == 422
