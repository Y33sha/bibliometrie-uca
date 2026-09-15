"""Plafond de débit commun à des requêtes simultanées (`RequestPace`)."""

import asyncio
import time

import pytest

from application.pipeline._fetch_pool import RequestPace


@pytest.mark.asyncio
async def test_spaces_request_starts_across_concurrent_workers():
    pace = RequestPace(max_per_second=50)  # un départ toutes les 20 ms
    starts: list[float] = []

    async def worker():
        for _ in range(5):
            await pace.wait()
            starts.append(time.monotonic())

    await asyncio.gather(*(worker() for _ in range(4)))
    starts.sort()
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    # Tolérance d'ordonnancement : les départs restent espacés d'environ 20 ms.
    assert min(gaps) >= 0.015
    assert starts[-1] - starts[0] >= 19 * 0.02 * 0.9


@pytest.mark.asyncio
async def test_first_request_starts_at_once():
    pace = RequestPace(max_per_second=1)
    before = time.monotonic()
    await pace.wait()
    assert time.monotonic() - before < 0.1
