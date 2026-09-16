"""Plafond de débit commun à des requêtes simultanées (`RequestPace`)."""

import asyncio
import time

import pytest

from application.pipeline._fetch_pool import RequestPace


@pytest.mark.asyncio
async def test_caps_the_start_rate_across_concurrent_workers():
    interval_s = 0.02
    pace = RequestPace(max_per_second=1 / interval_s)
    began_at = time.monotonic()
    starts: list[float] = []

    async def worker():
        for _ in range(5):
            await pace.wait()
            starts.append(time.monotonic() - began_at)

    await asyncio.gather(*(worker() for _ in range(4)))
    starts.sort()
    # Le k-ième départ vient au plus tôt k intervalles après le début : l'ordonnancement peut
    # retarder un worker, jamais avancer son départ. L'écart entre deux départs consécutifs, lui,
    # dépend de la boucle d'événements : une pause de celle-ci en rapproche deux qui rattrapent
    # leur retard, sans que le débit dépasse son plafond.
    for rank, start in enumerate(starts):
        assert start >= rank * interval_s


@pytest.mark.asyncio
async def test_first_request_starts_at_once():
    pace = RequestPace(max_per_second=1)
    before = time.monotonic()
    await pace.wait()
    assert time.monotonic() - before < 0.1
