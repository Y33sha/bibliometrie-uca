"""Accord en nombre des quantités affichées dans le journal."""

import pytest

from pipeline.runtime.observability.log_format import inflect, quantity, source_branch


@pytest.mark.parametrize(
    ("n", "attendu"),
    [(0, "0 préfixe"), (1, "1 préfixe"), (2, "2 préfixes"), (57, "57 préfixes")],
)
def test_le_singulier_couvre_zero_et_un(n: int, attendu: str) -> None:
    assert quantity(n, "préfixe") == attendu


def test_un_groupe_nominal_porte_son_pluriel() -> None:
    """Le `s` final se pose sur le nom, parfois placé ailleurs qu'en dernier dans le groupe."""
    assert quantity(5, "préfixe DOI", "préfixes DOI") == "5 préfixes DOI"


def test_une_annee_et_une_plage_gardent_la_meme_largeur() -> None:
    """La barre d'une source change d'année en cours de route sans décaler le reste de la ligne."""
    assert len(source_branch("hal", "2024")) == len(source_branch("hal", "2023-2026"))


def test_une_portee_vide_aligne_la_source_sur_les_autres() -> None:
    assert len(source_branch("theses", "")) == len(source_branch("hal", "2024"))


def test_sans_portee_le_libelle_s_arrete_au_nom() -> None:
    assert source_branch("hal").rstrip().endswith("HAL")


def test_la_forme_seule_sert_les_phrases_construites() -> None:
    assert f"3/5 {inflect(5, 'préfixe')} {inflect(5, 'résolu')}" == "3/5 préfixes résolus"
    assert f"1/1 {inflect(1, 'préfixe')} {inflect(1, 'résolu')}" == "1/1 préfixe résolu"
