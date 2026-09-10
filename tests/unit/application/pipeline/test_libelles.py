"""Accord en nombre des quantités affichées dans le journal."""

import pytest

from application.pipeline.libelles import accord, branche_de_source, forme


@pytest.mark.parametrize(
    ("n", "attendu"),
    [(0, "0 préfixe"), (1, "1 préfixe"), (2, "2 préfixes"), (57, "57 préfixes")],
)
def test_le_singulier_couvre_zero_et_un(n: int, attendu: str) -> None:
    assert accord(n, "préfixe") == attendu


def test_un_groupe_nominal_porte_son_pluriel() -> None:
    """Le `s` final se pose sur le nom, que le groupe ne place pas toujours en dernier."""
    assert accord(5, "préfixe DOI", "préfixes DOI") == "5 préfixes DOI"


def test_une_annee_et_une_plage_gardent_la_meme_largeur() -> None:
    """La barre d'une source change d'année en cours de route sans décaler le reste de la ligne."""
    assert len(branche_de_source("hal", "2024")) == len(branche_de_source("hal", "2023-2026"))


def test_une_portee_vide_aligne_la_source_sur_les_autres() -> None:
    assert len(branche_de_source("theses", "")) == len(branche_de_source("hal", "2024"))


def test_sans_portee_le_libelle_s_arrete_au_nom() -> None:
    assert branche_de_source("hal").rstrip().endswith("HAL")


def test_la_forme_seule_sert_les_phrases_construites() -> None:
    assert f"3/5 {forme(5, 'préfixe')} {forme(5, 'résolu')}" == "3/5 préfixes résolus"
    assert f"1/1 {forme(1, 'préfixe')} {forme(1, 'résolu')}" == "1/1 préfixe résolu"
