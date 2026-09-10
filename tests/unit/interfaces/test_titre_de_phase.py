"""Lignes ouvrant une exécution du pipeline, et chacune de ses phases."""

from __future__ import annotations

import argparse
import sys

import pytest

from application.pipeline.phase_order import PHASE_LIBELLES, PHASE_ORDER
from interfaces.cli.run_pipeline import LARGEUR_TITRE_PHASE, _titre_de_phase, _titre_du_run


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


def _args(**modifications) -> argparse.Namespace:
    defauts = {
        "mode": "full",
        "sources": "hal,openalex,scanr,theses,crossref,datacite,wos",
        "include_wos": False,
        "year": None,
        "start_year": None,
        "only": None,
        "from_phase": None,
        "no_extras": False,
        "rebuild_publications": False,
        "rebuild_authorships": False,
        "rebuild_subjects": False,
        "raw_store": False,
    }
    return argparse.Namespace(**{**defauts, **modifications})


def _texte(lignes: list[str]) -> str:
    return " ".join(lignes)


class TestTitreDuRun:
    def test_le_mode_parait(self, terminal) -> None:
        assert "mode ····· full" in _texte(_titre_du_run(_args(), []))

    def test_le_titre_ne_liste_pas_les_sources(self, terminal) -> None:
        """Chaque phase interroge ses propres sources : une liste commune induirait en erreur."""
        assert "sources" not in _texte(_titre_du_run(_args(), [])).lower()

    def test_une_annee_demandee_parait(self, terminal) -> None:
        assert "année ···· 2018" in _texte(_titre_du_run(_args(year=2018), []))

    def test_les_phases_paraissent_quand_le_lancement_les_restreint(self, terminal) -> None:
        texte = _texte(_titre_du_run(_args(only="persons"), [("persons", None)]))
        assert "phases ··· persons" in texte

    def test_un_lancement_courant_ne_liste_pas_les_phases(self, terminal) -> None:
        assert "phases" not in _texte(_titre_du_run(_args(), [("extract", None)]))

    def test_les_reconstructions_demandees_paraissent(self, terminal) -> None:
        texte = _texte(_titre_du_run(_args(rebuild_authorships=True), []))
        assert "options ·· signatures reconstruites" in texte
