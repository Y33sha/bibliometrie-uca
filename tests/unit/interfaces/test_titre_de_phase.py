"""Lignes ouvrant une phase du pipeline."""

from __future__ import annotations

import sys

import pytest

from application.pipeline.phase_order import PHASE_LIBELLES, PHASE_ORDER
from interfaces.cli.run_pipeline import LARGEUR_TITRE_PHASE, _titre_de_phase


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)


@pytest.fixture
def sortie_capturee(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)


@pytest.mark.parametrize("phase", PHASE_ORDER)
def test_les_cadres_ont_tous_la_meme_largeur(phase: str, terminal) -> None:
    """Des cadres inégaux se liraient comme des blocs sans rapport."""
    largeurs = {len(ligne) for ligne in _titre_de_phase(phase)}
    assert largeurs == {LARGEUR_TITRE_PHASE + 6}


@pytest.mark.parametrize("phase", PHASE_ORDER)
def test_chaque_cadre_porte_le_nom_et_le_libelle(phase: str, terminal) -> None:
    lignes = _titre_de_phase(phase)
    texte = " ".join(ligne.strip("║ ") for ligne in lignes)
    assert phase in texte
    for mot in PHASE_LIBELLES[phase].split():
        assert mot in texte


def test_un_libelle_long_tient_sur_deux_lignes(terminal) -> None:
    lignes = _titre_de_phase("authorships")
    assert len(lignes) == 5  # deux bords, le nom, et le libellé sur deux lignes


def test_une_sortie_capturee_recoit_des_filets(sortie_capturee) -> None:
    """Un fichier de journal ignore la largeur d'une fenêtre."""
    lignes = _titre_de_phase("normalize")
    assert lignes[0].startswith("─")
    assert "PHASE : normalize" in lignes[1]
    assert lignes[2] == PHASE_LIBELLES["normalize"]


def test_une_phase_sans_libelle_garde_son_cadre(terminal) -> None:
    """Les tests de l'orchestrateur nomment des phases hors du pipeline."""
    lignes = _titre_de_phase("une")
    assert len(lignes) == 3
    assert "une" in lignes[1]
