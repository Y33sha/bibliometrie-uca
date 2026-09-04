"""Tests unitaires du re-fetch des works OpenAlex tronqués.

Pas de réseau ni de base : un faux `OpenalexRefetchAdapter` sert des works scriptés, et la connexion est un mock. Ce qui est éprouvé ici est l'arbitrage du triage — le work qui dépasse cent auteurs est réécrit, celui qui en compte cent pile perd son marqueur sans réécriture, celui dont le fetch échoue garde le sien pour le run suivant.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from application.pipeline.extract.refetch_truncated import refetch
from application.ports.pipeline.extract.refetch_truncated import TruncatedWork

_LOGGER = logging.getLogger("test")


def _work(nb_auteurs: int) -> dict:
    return {"authorships": [{"author": {"id": f"A{i}"}} for i in range(nb_auteurs)]}


def _adapter(works: dict[str, dict | None]) -> MagicMock:
    """Faux adapter servant `works` indexé par identifiant OpenAlex ; `None` figure un fetch échoué."""
    a = MagicMock()
    a.max_concurrent = 2
    a.find_truncated.return_value = [
        TruncatedWork(staging_id=i, openalex_id=oid) for i, oid in enumerate(works, start=1)
    ]

    async def _fetch(client, openalex_id):
        return works[openalex_id]

    a.fetch_work.side_effect = _fetch
    return a


@pytest.mark.asyncio
async def test_aucun_work_tronque():
    adapter = _adapter({})
    metrics = await refetch(MagicMock(), adapter, _LOGGER)
    assert metrics.seen == 0
    adapter.fetch_work.assert_not_called()


@pytest.mark.asyncio
async def test_work_reellement_tronque_est_reecrit():
    adapter = _adapter({"W1": _work(150)})
    conn = MagicMock()
    metrics = await refetch(conn, adapter, _LOGGER)
    assert metrics.updated == 1
    adapter.update_raw_data.assert_called_once()
    adapter.clear_truncated.assert_not_called()


@pytest.mark.asyncio
async def test_work_a_cent_auteurs_pile_perd_son_marqueur():
    """Cent auteurs sans troncature : le marqueur s'efface, `raw_data` n'est pas réécrit."""
    adapter = _adapter({"W1": _work(100)})
    metrics = await refetch(MagicMock(), adapter, _LOGGER)
    assert metrics.extras.get("already_complete") == 1
    adapter.clear_truncated.assert_called_once()
    adapter.update_raw_data.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_echoue_garde_le_marqueur():
    adapter = _adapter({"W1": None})
    metrics = await refetch(MagicMock(), adapter, _LOGGER)
    assert metrics.errors == 1
    adapter.clear_truncated.assert_not_called()
    adapter.update_raw_data.assert_not_called()


@pytest.mark.asyncio
async def test_lot_mele():
    adapter = _adapter({"W1": _work(150), "W2": _work(100), "W3": None, "W4": _work(200)})
    metrics = await refetch(MagicMock(), adapter, _LOGGER)
    assert (metrics.seen, metrics.updated, metrics.errors) == (4, 2, 1)
    assert metrics.extras.get("already_complete") == 1
