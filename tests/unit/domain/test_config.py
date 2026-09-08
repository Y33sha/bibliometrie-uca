"""Forme imposée aux valeurs de configuration selon leur clé.

Le contrôle vaut à l'écriture, quelle que soit la voie : une valeur hors forme n'atteint pas la base.
"""

import pytest

from domain.config import MAX_YEAR, MIN_YEAR, normalize_config_value
from domain.errors import ValidationError

_PLAFOND = "unpaywall_max_per_run"
_ANNEE = "pipeline_start_year_full"


class TestPlafonds:
    def test_un_entier_positif_passe(self):
        assert normalize_config_value(_PLAFOND, 5000) == 5000

    def test_un_entier_ecrit_en_chaine_est_lu(self):
        assert normalize_config_value(_PLAFOND, "5000") == 5000

    def test_zero_retire_la_borne(self):
        assert normalize_config_value(_PLAFOND, 0) == 0

    @pytest.mark.parametrize("valeur", [None, "", "   "])
    def test_une_valeur_vide_retire_la_borne(self, valeur):
        assert normalize_config_value(_PLAFOND, valeur) == 0

    @pytest.mark.parametrize("valeur", [-1, "texte", True, 3.5, [], {}])
    def test_toute_autre_valeur_est_refusee(self, valeur):
        with pytest.raises(ValidationError, match="entier positif"):
            normalize_config_value(_PLAFOND, valeur)

    def test_le_second_plafond_suit_la_meme_regle(self):
        with pytest.raises(ValidationError, match="entier positif"):
            normalize_config_value("fetch_missing_max_per_source", "-4")


class TestAnnee:
    def test_une_annee_dans_les_bornes_passe(self):
        assert normalize_config_value(_ANNEE, 2017) == 2017

    def test_une_annee_ecrite_en_chaine_est_lue(self):
        assert normalize_config_value(_ANNEE, "2017") == 2017

    @pytest.mark.parametrize("valeur", [MIN_YEAR, MAX_YEAR])
    def test_les_bornes_sont_incluses(self, valeur):
        assert normalize_config_value(_ANNEE, valeur) == valeur

    @pytest.mark.parametrize("valeur", [MIN_YEAR - 1, MAX_YEAR + 1, "n", "", None, True, []])
    def test_hors_bornes_ou_illisible_est_refuse(self, valeur):
        with pytest.raises(ValidationError, match=str(MIN_YEAR)):
            normalize_config_value(_ANNEE, valeur)


def test_une_cle_sans_forme_imposee_passe_telle_quelle():
    assert normalize_config_value("perimeter_extraction", "alliance_uca") == "alliance_uca"
    assert normalize_config_value("laboratories_display_types", ["labo"]) == ["labo"]
