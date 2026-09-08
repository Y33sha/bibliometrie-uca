"""Appariement d'une ligne de relevé avec le type qu'elle alimente.

Le désaccord entre les colonnes d'un relevé et les champs d'un type échappe aux vérificateurs de types, le relevé étant une chaîne de caractères. Ces tests portent sur le contrôle qui le rattrape à l'exécution, et sur ce que son message nomme.
"""

from typing import NamedTuple

import pytest
from pydantic import BaseModel

from infrastructure.db.rows import row_as, rows_as


class _Ligne(NamedTuple):
    id: int
    titre: str
    annee: int | None = None


class _Modele(BaseModel):
    valeur: str
    compte: int


class _FausseLigne:
    """Ligne de relevé portant les colonnes données, telle que SQLAlchemy l'expose."""

    def __init__(self, **colonnes: object) -> None:
        self._colonnes = colonnes

    @property
    def _fields(self) -> tuple[str, ...]:
        return tuple(self._colonnes)

    @property
    def _mapping(self) -> dict[str, object]:
        return self._colonnes


def test_les_colonnes_alimentent_les_champs_de_meme_nom():
    ligne = row_as(_Ligne, _FausseLigne(id=1, titre="Titre", annee=2020))  # type: ignore[arg-type]
    assert ligne == _Ligne(id=1, titre="Titre", annee=2020)


def test_une_colonne_absente_laisse_le_champ_a_sa_valeur_par_defaut():
    ligne = row_as(_Ligne, _FausseLigne(id=1, titre="Titre"))  # type: ignore[arg-type]
    assert ligne.annee is None


def test_un_champ_exige_sans_colonne_leve():
    with pytest.raises(TypeError, match="champs qu'aucune colonne n'alimente : titre"):
        row_as(_Ligne, _FausseLigne(id=1))  # type: ignore[arg-type]


def test_une_colonne_que_le_type_n_attend_pas_leve():
    with pytest.raises(TypeError, match="colonnes que le type n'attend pas : editeur"):
        row_as(_Ligne, _FausseLigne(id=1, titre="Titre", editeur="Elsevier"))  # type: ignore[arg-type]


def test_le_message_nomme_le_type_vise():
    with pytest.raises(TypeError, match="_Ligne"):
        row_as(_Ligne, _FausseLigne(id=1))  # type: ignore[arg-type]


def test_les_deux_ecarts_paraissent_ensemble():
    with pytest.raises(TypeError, match="titre.*editeur"):
        row_as(_Ligne, _FausseLigne(id=1, editeur="Elsevier"))  # type: ignore[arg-type]


def test_un_modele_pydantic_s_apparie_comme_un_tuple_nomme():
    modele = row_as(_Modele, _FausseLigne(valeur="a", compte=3))  # type: ignore[arg-type]
    assert modele == _Modele(valeur="a", compte=3)


class _FauxReleve:
    """Relevé portant les colonnes données, telle que SQLAlchemy l'expose."""

    def __init__(self, colonnes: tuple[str, ...], lignes: list[_FausseLigne]) -> None:
        self._colonnes = colonnes
        self._lignes = lignes

    def keys(self) -> tuple[str, ...]:
        return self._colonnes

    def all(self) -> list[_FausseLigne]:
        return self._lignes


def test_plusieurs_lignes_se_construisent_ensemble():
    releve = _FauxReleve(
        ("id", "titre"), [_FausseLigne(id=1, titre="A"), _FausseLigne(id=2, titre="B")]
    )
    lignes = rows_as(_Ligne, releve)  # type: ignore[arg-type]
    assert [ligne.id for ligne in lignes] == [1, 2]


def test_un_releve_vide_fait_quand_meme_le_controle():
    """Le relevé nomme ses colonnes sans rendre de ligne : le désaccord paraît sur un ensemble vide."""
    releve = _FauxReleve(("id", "editeur"), [])
    with pytest.raises(TypeError, match="titre.*editeur"):
        rows_as(_Ligne, releve)  # type: ignore[arg-type]


def test_un_releve_vide_qui_s_accorde_rend_une_liste_vide():
    assert rows_as(_Ligne, _FauxReleve(("id", "titre"), [])) == []  # type: ignore[arg-type]
