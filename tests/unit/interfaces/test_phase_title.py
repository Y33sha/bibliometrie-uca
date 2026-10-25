"""Lignes ouvrant une exécution du pipeline, et chacune de ses phases."""

from __future__ import annotations

import argparse
import contextlib
import sys

import pytest

from pipeline.graph import PHASE_LABELS, PHASE_ORDER
from pipeline.run import (
    PHASE_TITLE_WIDTH,
    _build_arg_parser,
    _phase_label,
    _phase_title,
    _run_title,
)


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)


@pytest.fixture
def sortie_capturee(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)


@pytest.fixture
def delai_de_rafraichissement(monkeypatch):
    """Configuration lue par les libellés de phase, sans base : les documents se rafraîchissent après 7 jours."""
    delay_days = {"jours": 7}
    monkeypatch.setattr("pipeline.run.open_tx", contextlib.nullcontext)
    monkeypatch.setattr("pipeline.run.delay", lambda conn, key: delay_days["jours"])
    return delay_days


def _titre(phase: str) -> list[str]:
    return _phase_title(phase, _phase_label(phase))


@pytest.mark.parametrize("phase", PHASE_ORDER)
def test_les_cadres_ont_tous_la_meme_largeur(
    phase: str, terminal, delai_de_rafraichissement
) -> None:
    """Des cadres inégaux se liraient comme des blocs sans rapport."""
    largeurs = {len(line) for line in _titre(phase)}
    assert largeurs == {PHASE_TITLE_WIDTH + 6}


@pytest.mark.parametrize("phase", PHASE_ORDER)
def test_chaque_cadre_porte_le_nom_et_le_libelle(
    phase: str, terminal, delai_de_rafraichissement
) -> None:
    lines = _titre(phase)
    text = " ".join(line.strip("║ ") for line in lines)
    assert phase in text
    for mot in _phase_label(phase).split():
        assert mot in text


@pytest.mark.parametrize("phase", PHASE_ORDER)
def test_chaque_libelle_a_tous_ses_champs_remplis(phase: str, delai_de_rafraichissement) -> None:
    assert "{" not in _phase_label(phase)


def test_le_libelle_de_fetch_stale_donne_le_delai(delai_de_rafraichissement) -> None:
    assert _phase_label("fetch_stale") == "Recherche des documents non revus depuis 7 jours"
    delai_de_rafraichissement["jours"] = 1
    assert _phase_label("fetch_stale") == "Recherche des documents non revus depuis 1 jour"


def test_un_libelle_long_tient_sur_deux_lignes(terminal) -> None:
    lines = _titre("finalize")
    assert len(lines) == 5  # deux bords, le nom, et le libellé sur deux lignes


def test_une_sortie_capturee_recoit_des_filets(sortie_capturee) -> None:
    """Un fichier de journal ignore la largeur d'une fenêtre."""
    lines = _titre("normalize")
    assert lines[0].startswith("─")
    assert "PHASE : normalize" in lines[1]
    assert lines[2] == PHASE_LABELS["normalize"]


def test_une_phase_sans_libelle_garde_son_cadre(terminal) -> None:
    """Les tests de l'orchestrateur nomment des phases hors du pipeline."""
    lines = _titre("une")
    assert len(lines) == 3
    assert "une" in lines[1]


def _args(**modifications) -> argparse.Namespace:
    """Arguments par défaut de la CLI, puis `modifications`."""
    return argparse.Namespace(**{**vars(_build_arg_parser().parse_args([])), **modifications})


def _texte(lines: list[str]) -> str:
    return " ".join(lines)


class TestTitreDuRun:
    def test_le_mode_parait(self, terminal) -> None:
        assert "mode ····· full" in _texte(_run_title(_args(), []))

    def test_le_titre_ne_liste_pas_les_sources(self, terminal) -> None:
        """Chaque phase interroge ses propres sources : une liste commune induirait en erreur."""
        assert "sources" not in _texte(_run_title(_args(), [])).lower()

    def test_une_annee_demandee_parait(self, terminal) -> None:
        assert "année ···· 2018" in _texte(_run_title(_args(year=2018), []))

    def test_les_phases_paraissent_quand_le_lancement_les_restreint(self, terminal) -> None:
        text = _texte(_run_title(_args(only="persons"), [("persons", None)]))
        assert "phases ··· persons" in text

    def test_un_lancement_courant_ne_liste_pas_les_phases(self, terminal) -> None:
        assert "phases" not in _texte(_run_title(_args(), [("harvest", None)]))

    def test_les_reconstructions_demandees_paraissent(self, terminal) -> None:
        text = _texte(_run_title(_args(rebuild_subjects=True), []))
        assert "options ·· sujets reconstruits" in text
