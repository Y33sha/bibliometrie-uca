"""Relecture des works OpenAlex tronqués (`pipeline.ingestion.openalex.fetch_truncated`).

Pas de réseau ni de base : la lecture d'un work est simulée, et une connexion simulée renvoie les works marqués et retient les écritures. Les tests vérifient le triage : le work qui dépasse cent auteurs est réécrit ; celui qui en compte exactement cent perd son marqueur sans réécriture ; celui qui est absent d'OpenAlex perd son marqueur ; celui dont OpenAlex est indisponible garde son marqueur pour le run suivant.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from domain.sources.registry import ALL_SOURCES_SET
from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.ingestion.common import staging
from pipeline.ingestion.openalex import fetch_truncated
from pipeline.ingestion.openalex.fetch_truncated import FetchTruncatedPhase, refetch_openalex

_LOGGER = logging.getLogger("test")


def _work(nb_auteurs: int) -> dict:
    return {"authorships": [{"author": {"id": f"A{i}"}} for i in range(nb_auteurs)]}


class _Connexion:
    """Connexion simulée : renvoie les works marqués, retient les réécritures et les marqueurs levés."""

    def __init__(self, openalex_ids) -> None:
        self._ids = list(openalex_ids)
        self.reecrits: list[str] = []
        self.leves: list[str] = []

    def execute(self, sql, params=None):
        if sql is fetch_truncated._SELECT_TRUNCATED_SQL:
            return SimpleNamespace(scalars=lambda: self._ids)
        if sql is staging._COMPLETE_AUTHORS_SQL:
            self.reecrits.append(params["source_id"])
        elif sql is staging._CLEAR_TRUNCATED_SQL:
            self.leves.append(params["source_id"])
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


async def test_work_inconnu_d_openalex_perd_son_marqueur(openalex):
    """Work supprimé ou fusionné dans OpenAlex : le marqueur s'efface, donc le run suivant ignore le work."""
    conn = openalex({"W1": NOT_FOUND})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert metrics.extras.get("not_found") == 1
    assert (conn.reecrits, conn.leves) == ([], ["W1"])


@pytest.mark.parametrize(
    ("works", "titre"),
    [
        ({"W1": _work(100)}, "▶ 1 document de 100 auteurs, potentiellement tronqué"),
        (
            {"W1": _work(100), "W2": _work(150)},
            "▶ 2 documents de 100 auteurs, potentiellement tronqués",
        ),
    ],
)
async def test_l_etape_annonce_les_documents_a_verifier(openalex, works, titre, caplog):
    with caplog.at_level(logging.INFO, logger="test"):
        await refetch_openalex(openalex(works), _LOGGER)
    assert titre in caplog.messages


async def test_lot_mele(openalex):
    conn = openalex({"W1": _work(150), "W2": _work(100), "W3": UNAVAILABLE, "W4": _work(200)})
    metrics = await refetch_openalex(conn, _LOGGER)
    assert (metrics.seen, metrics.updated, metrics.errors) == (4, 2, 1)
    assert metrics.unchanged == 1


def test_phase_sautee_sans_openalex_dans_les_sources(open_tx, contexte):
    metrics = FetchTruncatedPhase().run(contexte(sources={"hal"}))
    assert metrics.seen == 0
    assert open_tx.transactions == 0


@pytest.mark.parametrize("sources", [ALL_SOURCES_SET, {"openalex"}])
def test_phase_tourne_avec_openalex_dans_les_sources(monkeypatch, open_tx, contexte, sources):
    async def _refetch(conn, log):
        return fetch_truncated.PhaseMetrics(updated=1)

    monkeypatch.setattr(fetch_truncated, "refetch_openalex", _refetch)
    metrics = FetchTruncatedPhase().run(contexte(sources=sources))
    assert metrics.updated == 1
    assert open_tx.transactions == 1
