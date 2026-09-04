"""Tests unitaires de l'orchestrateur d'extraction theses.fr.

Pas de réseau ni de base : un faux `ThesesExtractAdapter` sert des pages scriptées, et la connexion est un mock dont seul `commit` est appelé. Ce qui est éprouvé ici est le pilotage — pagination sur `totalHits`, filtre par année sur le préfixe du NNT, comptage du routage rendu par l'upsert, arrêt sur circuit-breaker.
"""

from __future__ import annotations

import argparse
import logging
from unittest.mock import MagicMock

from application.pipeline.extract.extract_theses import ThesesExtractor, extract_ppn
from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.theses import ThesesExtractConfig

_LOGGER = logging.getLogger("test")


def _adapter(pages: list[list[dict]], *, total: int | None = None) -> MagicMock:
    """Faux adapter servant `pages` successivement.

    Chaque thèse porte son identifiant en `id` et le sort que lui réserve l'upsert en `_route`.
    """
    a = MagicMock()
    a.build_query.return_value = "q"
    a.per_page.return_value = 100
    a.extract_id.side_effect = lambda these: these.get("id", "")
    a.upsert_these.side_effect = lambda conn, these: these["_route"]

    total_hits = total if total is not None else sum(len(p) for p in pages)
    reponses = [{"totalHits": total_hits}] + [{"theses": p} for p in pages]
    a.fetch_page.side_effect = reponses
    return a


def _these(identifiant: str, route: UpsertOutcome = UpsertOutcome.NEW) -> dict:
    return {"id": identifiant, "_route": route}


def test_pagination_jusqu_au_total():
    adapter = _adapter([[_these("2020AAA1"), _these("2020AAA2")], [_these("2020AAA3")]], total=3)
    total, nouveaux, majs, inchanges = extract_ppn(adapter, MagicMock(), "PPN1", _LOGGER)
    assert (total, nouveaux, majs, inchanges) == (3, 3, 0, 0)


def test_routage_par_sort_de_l_upsert():
    adapter = _adapter(
        [
            [
                _these("2020A", UpsertOutcome.NEW),
                _these("2020B", UpsertOutcome.UPDATED),
                _these("2020C", UpsertOutcome.UNCHANGED),
            ]
        ]
    )
    assert extract_ppn(adapter, MagicMock(), "PPN1", _LOGGER) == (3, 1, 1, 1)


def test_filtre_annee_sur_le_prefixe_du_nnt():
    adapter = _adapter([[_these("2020AAA1"), _these("2021AAA1")]])
    total, nouveaux, _, _ = extract_ppn(adapter, MagicMock(), "PPN1", _LOGGER, year=2021)
    assert (total, nouveaux) == (2, 1)


def test_these_sans_identifiant_ignoree():
    adapter = _adapter([[_these(""), _these("2020AAA1")]])
    assert extract_ppn(adapter, MagicMock(), "PPN1", _LOGGER)[1] == 1


def test_dry_run_ne_pagine_pas():
    adapter = _adapter([[_these("2020AAA1")]], total=1)
    assert extract_ppn(adapter, MagicMock(), "PPN1", _LOGGER, dry_run=True) == (1, 0, 0, 0)
    assert adapter.fetch_page.call_count == 1


def test_aucun_resultat():
    adapter = _adapter([], total=0)
    assert extract_ppn(adapter, MagicMock(), "PPN1", _LOGGER) == (0, 0, 0, 0)


def test_page_vide_interrompt_la_boucle():
    """`totalHits` annonce plus que ce que la source sert : la boucle s'arrête sans tourner à vide."""
    adapter = _adapter([[]], total=10)
    assert extract_ppn(adapter, MagicMock(), "PPN1", _LOGGER) == (10, 0, 0, 0)


def _extracteur(adapter: MagicMock, ppns: list[str]) -> ThesesExtractor:
    adapter.load_config.return_value = ThesesExtractConfig(base_url="https://example/", ppns=ppns)
    return ThesesExtractor(MagicMock(), _LOGGER, adapter)


def test_run_parcourt_chaque_etablissement():
    adapter = _adapter([[_these("2020A")], [_these("2020B")]], total=1)
    adapter.fetch_page.side_effect = [
        {"totalHits": 1},
        {"theses": [_these("2020A")]},
        {"totalHits": 1},
        {"theses": [_these("2020B")]},
    ]
    metrics = _extracteur(adapter, ["PPN1", "PPN2"]).run(
        argparse.Namespace(dry_run=False, year=None)
    )
    assert metrics.new == 2


def test_run_sans_ppn_configure_refuse():
    import pytest

    from application.pipeline.extract.base import ExtractionConfigError

    adapter = _adapter([], total=0)
    with pytest.raises(ExtractionConfigError, match="aucun PPN"):
        _extracteur(adapter, []).run(argparse.Namespace(dry_run=False, year=None))


def test_run_s_arrete_quand_la_source_est_a_bout():
    """Le circuit-breaker tripé laisse les établissements restants au run suivant."""
    adapter = _adapter([[_these("2020A")]], total=1)
    breaker = MagicMock()
    breaker.tripped = True
    metrics = _extracteur(adapter, ["PPN1", "PPN2"]).run(
        argparse.Namespace(dry_run=False, year=None), breaker=breaker
    )
    assert metrics.total == 0
    assert adapter.fetch_page.call_count == 0
