"""Rythme des requêtes à une source (`Pace`) : plafond de débit commun aux requêtes simultanées comme aux requêtes synchrones."""

import asyncio
import time

import pytest

from pipeline.http.pace import Pace


@pytest.mark.asyncio
async def test_caps_the_start_rate_across_concurrent_workers():
    interval_s = 0.02
    pace = Pace(max_per_second=1 / interval_s)
    began_at = time.monotonic()
    starts: list[float] = []

    async def worker():
        for _ in range(5):
            await pace.wait_async()
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
    pace = Pace(max_per_second=1)
    before = time.monotonic()
    await pace.wait_async()
    assert time.monotonic() - before < 0.1


def test_synchronous_requests_share_the_same_cap():
    interval_s = 0.02
    pace = Pace(max_per_second=1 / interval_s)
    began_at = time.monotonic()
    for _ in range(3):
        pace.wait()
    assert time.monotonic() - began_at >= 2 * interval_s
