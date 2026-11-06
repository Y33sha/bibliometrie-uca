"""Relecture des works OpenAlex tronqués (`pipeline.ingestion.openalex.fetch_truncated`).

Pas de réseau ni de base : la lecture d'un work est simulée, et une connexion simulée renvoie les works marqués et retient les écritures. Les tests vérifient le triage :
- un work à plus de cent auteurs est réécrit ;
- un work à cent auteurs exactement perd son marqueur sans réécriture ;
- un work absent d'OpenAlex, ou fusionné dans un autre work, est marqué disparu et garde son marqueur ;
- un work lu pendant une indisponibilité d'OpenAlex garde son marqueur pour le run suivant.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from domain.sources.registry import Source
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.ingestion.common import staging
from pipeline.ingestion.openalex import fetch_truncated
from pipeline.ingestion.openalex.fetch_truncated import refetch_openalex
from pipeline.task_runner import execute_tasks

_LOGGER = logging.getLogger("test")


def _work(nb_auteurs: int) -> dict:
    return {"authorships": [{"author": {"id": f"A{i}"}} for i in range(nb_auteurs)]}


class _Connexion:
    """Connexion simulée : renvoie les works marqués, retient les réécritures, les marqueurs levés et les works marqués disparus."""

    def __init__(self, openalex_ids) -> None:
        self._ids = list(openalex_ids)
        self.reecrits: list[str] = []
        self.leves: list[str] = []
        self.disparus: list[str] = []

    def execute(self, sql, params=None):
        if sql is fetch_truncated._SELECT_TRUNCATED_SQL:
            return SimpleNamespace(scalars=lambda: self._ids)
        if sql is staging._COMPLETE_AUTHORS_SQL:
            self.reecrits.append(params["source_id"])
        elif sql is staging._CLEAR_TRUNCATED_SQL:
            self.leves.append(params["source_id"])
        elif sql is staging._MARK_DISAPPEARED_SQL:
            self.disparus.append(params["source_id"])
        return None

    def commit(self) -> None:
        pass


@pytest.fixture
def openalex(monkeypatch):
    """Pose les réponses d'OpenAlex, indexées par identifiant : un work, `NOT_FOUND` ou `UNAVAILABLE`. Renvoie la connexion simulée."""

    def _poser(works: dict) -> _Connexion:
        async def _fetch(client, openalex_id):
            work = works[openalex_id]
            return (
                {"id": f"https://openalex.org/{openalex_id}", **work}
                if isinstance(work, dict)
                else work
            )

        monkeypatch.setattr(fetch_truncated, "fetch_work", _fetch)
        return _Connexion(works)

    return _poser


async def test_aucun_work_tronque(openalex):
    metrics = await refetch_openalex(openalex({}), _LOGGER)
    assert metrics.seen == 0


async def test_work_reellement_tronque_est_reecrit(openalex):
    conn = openalex({"W1": _work(150)})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert metrics.updated == 1
    assert (conn.reecrits, conn.leves) == (["W1"], [])


async def test_work_a_cent_auteurs_pile_perd_son_marqueur(openalex):
    """Cent auteurs sans troncature : le marqueur s'efface, `raw_data` reste tel quel."""
    conn = openalex({"W1": _work(100)})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert metrics.unchanged == 1
    assert (conn.reecrits, conn.leves) == ([], ["W1"])


async def test_openalex_indisponible_garde_le_marqueur(openalex):
    conn = openalex({"W1": UNAVAILABLE})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert metrics.errors == 1
    assert (conn.reecrits, conn.leves) == ([], [])


async def test_work_inconnu_d_openalex_est_marque_disparu(openalex):
    """Work supprimé dans OpenAlex : marqué disparu, il garde son marqueur."""
    conn = openalex({"W1": NOT_FOUND})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert metrics.extras.get("disappeared") == 1
    assert (conn.reecrits, conn.leves, conn.disparus) == ([], [], ["W1"])


async def test_work_fusionne_est_marque_disparu(openalex):
    """Work fusionné : OpenAlex renvoie le work absorbant, écrit sous son identifiant ; le work demandé est marqué disparu."""
    conn = openalex({"W1": {"id": "https://openalex.org/W9", **_work(150)}})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert metrics.extras.get("disappeared") == 1
    assert (conn.reecrits, conn.leves, conn.disparus) == (["W9"], [], ["W1"])


async def test_lot_mele(openalex):
    conn = openalex({"W1": _work(150), "W2": _work(100), "W3": UNAVAILABLE, "W4": _work(200)})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert (metrics.seen, metrics.updated, metrics.errors) == (4, 2, 1)
    assert metrics.unchanged == 1


def test_phase_sautee_sans_openalex_dans_les_sources(open_tx, contexte):
    assert execute_tasks(fetch_truncated.TASKS, contexte(sources={"hal"})) == {}
    assert open_tx.transactions == 0


@pytest.mark.parametrize("sources", [frozenset(Source), {"openalex"}])
def test_phase_tourne_avec_openalex_dans_les_sources(monkeypatch, open_tx, contexte, sources):
    async def _refetch(conn, log):
        return fetch_truncated.PhaseMetrics(updated=1)

    monkeypatch.setattr(fetch_truncated, "refetch_openalex", _refetch)
    (metrics,) = execute_tasks(fetch_truncated.TASKS, contexte(sources=sources)).values()
    assert metrics.updated == 1
    assert open_tx.transactions == 1
