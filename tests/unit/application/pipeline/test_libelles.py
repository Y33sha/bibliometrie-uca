"""Accord en nombre des quantités affichées dans le journal."""

import pytest

from application.pipeline.libelles import accord, forme


@pytest.mark.parametrize(
    ("n", "attendu"),
    [(0, "0 préfixe"), (1, "1 préfixe"), (2, "2 préfixes"), (57, "57 préfixes")],
)
def test_le_singulier_couvre_zero_et_un(n: int, attendu: str) -> None:
    assert accord(n, "préfixe") == attendu


def test_un_groupe_nominal_porte_son_pluriel() -> None:
    """Le `s` final se pose sur le nom, que le groupe ne place pas toujours en dernier."""
    assert accord(5, "préfixe DOI", "préfixes DOI") == "5 préfixes DOI"


def test_la_forme_seule_sert_les_phrases_construites() -> None:
    assert f"3/5 {forme(5, 'préfixe')} {forme(5, 'résolu')}" == "3/5 préfixes résolus"
    assert f"1/1 {forme(1, 'préfixe')} {forme(1, 'résolu')}" == "1/1 préfixe résolu"
