"""Forme imposée aux valeurs de configuration selon leur clé.

Le contrôle vaut à l'écriture, quelle que soit la voie : une valeur hors forme n'atteint pas la base.
"""

import pytest

from domain.config import (
    DEFAULT_START_YEAR_OFFSET,
    ConfigKey,
    integer_bounds,
    normalize_config_value,
    start_year_value,
)
from domain.errors import NotFoundError, ValidationError

MIN_YEAR, MAX_YEAR = integer_bounds(ConfigKey.PIPELINE_START_YEAR_FULL)

_PLAFOND = "unpaywall_max_per_run"
_ANNEE = "pipeline_start_year_full"
_DELAI = "fetch_stale_after_days"


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

    @pytest.mark.parametrize("valeur", [-1, 10_000_001, "texte", True, 3.5, [], {}])
    def test_toute_autre_valeur_est_refusee(self, valeur):
        with pytest.raises(ValidationError, match="entier de 0 à"):
            normalize_config_value(_PLAFOND, valeur)

    def test_le_second_plafond_suit_la_meme_regle(self):
        with pytest.raises(ValidationError, match="entier de 0 à"):
            normalize_config_value("fetch_missing_max_per_source", "-4")


class TestAnnee:
    def test_une_annee_dans_les_bornes_passe(self):
        assert normalize_config_value(_ANNEE, 2017) == 2017

    def test_une_annee_ecrite_en_chaine_est_lue(self):
        assert normalize_config_value(_ANNEE, "2017") == 2017

    @pytest.mark.parametrize("valeur", [MIN_YEAR, MAX_YEAR])
    def test_les_bornes_sont_incluses(self, valeur):
        assert normalize_config_value(_ANNEE, valeur) == valeur

    @pytest.mark.parametrize("valeur", [None, "", "   "])
    def test_une_valeur_vide_laisse_l_annee_non_fixee(self, valeur):
        assert normalize_config_value(_ANNEE, valeur) is None

    @pytest.mark.parametrize("valeur", [MIN_YEAR - 1, MAX_YEAR + 1, "n", True, []])
    def test_hors_bornes_ou_illisible_est_refuse(self, valeur):
        with pytest.raises(ValidationError, match=str(MIN_YEAR)):
            normalize_config_value(_ANNEE, valeur)

    def test_une_annee_fixee_est_retenue(self):
        assert start_year_value(2017, current_year=2026) == 2017

    def test_sans_annee_fixee_la_premiere_annee_suit_l_annee_courante(self):
        assert start_year_value(None, current_year=2026) == 2026 - DEFAULT_START_YEAR_OFFSET


class TestDelais:
    def test_un_nombre_de_jours_passe(self):
        assert normalize_config_value(_DELAI, 90) == 90

    def test_un_nombre_ecrit_en_chaine_est_lu(self):
        assert normalize_config_value(_DELAI, "30") == 30

    @pytest.mark.parametrize("valeur", [0, -1, 3651, None, "", "texte", True, 1.5, []])
    def test_hors_bornes_ou_illisible_est_refuse(self, valeur):
        with pytest.raises(ValidationError, match="entier de 1 à 3650"):
            normalize_config_value(_DELAI, valeur)


class TestTitre:
    def test_les_espaces_de_bord_sont_retires(self):
        assert (
            normalize_config_value(ConfigKey.SITE_TITLE, "  Bibliométrie Test ")
            == "Bibliométrie Test"
        )

    @pytest.mark.parametrize("valeur", [None, "", "   "])
    def test_un_titre_absent_vaut_un_texte_vide(self, valeur):
        assert normalize_config_value(ConfigKey.SITE_TITLE, valeur) == ""

    @pytest.mark.parametrize("valeur", [3, True, [], {}])
    def test_une_valeur_autre_qu_un_texte_est_refusee(self, valeur):
        with pytest.raises(ValidationError, match="texte"):
            normalize_config_value(ConfigKey.SITE_TITLE, valeur)


class TestTeinte:
    @pytest.mark.parametrize(("valeur", "attendu"), [(0, 0), (359, 359), ("  120 ", 120)])
    def test_un_angle_entier_est_retenu(self, valeur, attendu):
        assert normalize_config_value(ConfigKey.BRAND_HUE, valeur) == attendu

    @pytest.mark.parametrize("valeur", [-1, 360, 12.5, "rouge", None, True])
    def test_une_valeur_hors_de_0_a_359_est_refusee(self, valeur):
        with pytest.raises(ValidationError, match="0 à 359"):
            normalize_config_value(ConfigKey.BRAND_HUE, valeur)


class TestPaysEtablissement:
    def test_le_code_est_ramene_en_minuscules(self):
        assert normalize_config_value(ConfigKey.INSTITUTION_COUNTRY, " BE ") == "be"

    @pytest.mark.parametrize("valeur", [None, "", "fra", "xx", 33, ["fr"]])
    def test_une_valeur_autre_qu_un_code_pays_est_refusee(self, valeur):
        with pytest.raises(ValidationError, match="code pays"):
            normalize_config_value(ConfigKey.INSTITUTION_COUNTRY, valeur)


class TestTypesDeLaboratoire:
    def test_les_types_sont_dedoublonnes_dans_l_ordre_de_l_enum(self):
        assert normalize_config_value(ConfigKey.LABORATORY_TYPES, ["admin", "labo", "admin"]) == [
            "labo",
            "admin",
        ]

    @pytest.mark.parametrize("valeur", [None, [], "labo"])
    def test_une_valeur_autre_qu_une_liste_non_vide_est_refusee(self, valeur):
        with pytest.raises(ValidationError, match="liste non vide"):
            normalize_config_value(ConfigKey.LABORATORY_TYPES, valeur)

    def test_un_type_inconnu_est_refuse(self):
        with pytest.raises(ValidationError, match="inconnus"):
            normalize_config_value(ConfigKey.LABORATORY_TYPES, ["labo", "institut"])


def test_une_cle_sans_forme_imposee_passe_telle_quelle():
    assert normalize_config_value("perimeter_extraction", "alliance_uca") == "alliance_uca"


def test_une_cle_inconnue_est_refusee():
    with pytest.raises(NotFoundError, match="introuvable"):
        normalize_config_value("cle_inconnue", "x")
