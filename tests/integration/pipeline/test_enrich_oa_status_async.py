"""Tests pour `application.pipeline.oa_status.phase.run` (async).

Couvre la version async via `httpx2.AsyncClient` + `asyncio.Semaphore`,
end-to-end avec le `fetcher` concret depuis `infrastructure.sources.unpaywall.client` :
- happy path (3 publis, statuts mappés, update DB)
- 404 Unpaywall → `not_found`
- préservation `diamond` quand Unpaywall renvoie `gold`
- statut inchangé → `skipped`, pas d'update
- dry_run → pas d'update DB
- 429 retry transparent (géré par `http_request_with_retry_async`)
- semaphore plafonne les fetches concurrents

Mocks : port `OaStatusQueries` (lectures + écritures capturées) ; requêtes HTTP via la fixture `http_mock`.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import httpx2
import pytest

from application.pipeline.oa_status import phase as module
from infrastructure.sources.unpaywall.client import fetch_oa_status

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
TEST_EMAIL = "test@example.com"


def _make_fetcher(logger: logging.Logger):
    """Compose le fetcher infrastructure pour les tests (couverture end-to-end)."""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> str | None:
        return await fetch_oa_status(
            client, doi, base_url=UNPAYWALL_BASE, email=TEST_EMAIL, logger=logger
        )

    return fetcher


def _route(http_mock, doi: str, *, status: str | None = None, http_status: int = 200):
    """Déclare la réponse Unpaywall servie pour un DOI.

    `status` = chaîne Unpaywall (`'gold'`, `'closed'`, etc.) ou None pour
    `http_status=404`. Si `http_status != 200/404`, on renvoie ce status
    avec un body vide.
    """
    body = {"oa_status": status} if status is not None else None
    return http_mock.get(f"{UNPAYWALL_BASE}/{doi}").mock(
        return_value=httpx2.Response(http_status, json=body)
    )


class _FakeQueries:
    """Lectures de la file OA et capture des écritures (`update_oa_status`, `mark_unpaywall_checked`)."""

    def __init__(
        self,
        pubs: list[tuple[int, str, str | None, bool]],
        *,
        stale_total: int | None = None,
        oa_distribution: dict[str, int] | None = None,
    ) -> None:
        self._pubs = pubs
        self._stale_total = stale_total if stale_total is not None else len(pubs)
        self._oa_distribution = oa_distribution or {}
        self.updates: list[tuple[int, str]] = []
        self.checked: list[int] = []

    def fetch_publications_with_doi(self, conn, *, limit=None, staleness_days):  # noqa: ARG002
        return self._pubs[:limit] if limit else self._pubs

    def count_stale_publications(self, conn, *, staleness_days) -> int:  # noqa: ARG002
        return self._stale_total

    def count_publications_by_oa_status(self, conn) -> dict[str, int]:  # noqa: ARG002
        return dict(self._oa_distribution)

    def update_oa_status(self, conn, pub_id: int, status: str) -> None:  # noqa: ARG002
        self.updates.append((pub_id, status))

    def mark_unpaywall_checked(self, conn, pub_id: int) -> None:  # noqa: ARG002
        self.checked.append(pub_id)


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_enrich_oa_status")


@pytest.mark.asyncio
async def test_happy_path_updates_each_pub(logger, http_mock):
    pubs = [
        (1, "10.1/a", "closed", False),
        (2, "10.1/b", None, False),
        (3, "10.1/c", "bronze", False),
    ]
    _route(http_mock, "10.1/a", status="gold")
    _route(http_mock, "10.1/b", status="green")
    _route(http_mock, "10.1/c", status="bronze")

    queries = _FakeQueries(pubs, stale_total=42, oa_distribution={"gold": 7, "closed": 3})
    metrics = await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )

    # pub 3 inchangée (bronze→bronze), 1 et 2 mises à jour
    assert sorted(queries.updates) == [(1, "gold"), (2, "green")]
    # Indicateurs remontés : compteurs du run, backlog stale, ventilation + table OA.
    assert metrics.total == 3
    assert metrics.updated == 2
    assert metrics.unchanged == 1
    assert metrics.extras["not_found"] == 0
    assert metrics.extras["stale"] == 42
    summary = metrics.details["summary"]
    assert summary["stale"] == 42
    assert summary["checked"] == 3
    assert summary["updated"] == 2
    # before == after (fake renvoie la même distribution) → delta nul, trié par count.
    assert metrics.details["table"]["rows"][0] == {"key": "gold", "count": 7, "delta": 0}


@pytest.mark.asyncio
async def test_404_marks_as_not_found(logger, http_mock):
    pubs = [(1, "10.1/x", "closed", False)]
    _route(http_mock, "10.1/x", http_status=404)

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == []
    assert queries.checked == [1]  # marqué vérifié même si non trouvé (pas re-tiré demain)


@pytest.mark.asyncio
async def test_diamond_not_replaced_by_gold(logger, http_mock):
    """Diamond OA n'est pas connu d'Unpaywall : ne pas écraser par 'gold'."""
    pubs = [(1, "10.1/diamond", "diamond", False)]
    _route(http_mock, "10.1/diamond", status="gold")

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == []


@pytest.mark.asyncio
async def test_diamond_replaced_by_other_status(logger, http_mock):
    """Diamond → bronze/green/closed : on accepte l'update (seul gold est filtré)."""
    pubs = [(1, "10.1/diamond", "diamond", False)]
    _route(http_mock, "10.1/diamond", status="bronze")

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == [(1, "bronze")]


@pytest.mark.asyncio
async def test_embargoed_not_downgraded_to_closed(logger, http_mock):
    """Embargo connu (HAL) : Unpaywall voit le fichier non encore accessible et
    renvoie 'closed' — on ne rétrograde pas vers closed/unknown."""
    pubs = [(1, "10.1/emb", "embargoed", False)]
    _route(http_mock, "10.1/emb", status="closed")

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == []


@pytest.mark.asyncio
async def test_embargoed_replaced_by_open_status(logger, http_mock):
    """Embargo → green/gold : un statut réellement plus ouvert (trouvé ailleurs) écrase bien."""
    pubs = [(1, "10.1/emb", "embargoed", False)]
    _route(http_mock, "10.1/emb", status="green")

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == [(1, "green")]


@pytest.mark.asyncio
async def test_open_archive_deposit_not_downgraded_to_closed(logger, http_mock):
    """Une archive ouverte détient le fichier (HAL green, `has_open_deposit=True`) : Unpaywall ne le
    voit pas sous le DOI et renvoie 'closed' — on ne referme pas le dépôt, mais on marque vérifié."""
    pubs = [(1, "10.1/deposit", "green", True)]
    _route(http_mock, "10.1/deposit", status="closed")

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == []
    assert queries.checked == [1]


@pytest.mark.asyncio
async def test_open_archive_deposit_upgraded_by_unpaywall(logger, http_mock):
    """Le garde-fou ne bloque que les rétrogradations : un statut plus ouvert (gold) écrase bien,
    même avec un dépôt-archive."""
    pubs = [(1, "10.1/deposit", "green", True)]
    _route(http_mock, "10.1/deposit", status="gold")

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == [(1, "gold")]


@pytest.mark.asyncio
async def test_unchanged_status_skipped(logger, http_mock):
    pubs = [(1, "10.1/same", "gold", False)]
    _route(http_mock, "10.1/same", status="gold")

    queries = _FakeQueries(pubs)
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == []
    assert queries.checked == [1]  # statut inchangé mais marqué vérifié


@pytest.mark.asyncio
async def test_429_retries_transparently(logger, http_mock):
    """Un 429 puis 200 : `http_request_with_retry_async` re-essaie en interne."""
    http_mock.get(f"{UNPAYWALL_BASE}/10.1/r").mock(
        side_effect=[
            httpx2.Response(429),
            httpx2.Response(200, json={"oa_status": "green"}),
        ]
    )

    queries = _FakeQueries([(1, "10.1/r", "closed", False)])
    await module.run(
        MagicMock(),
        queries,
        logger,
        fetcher=_make_fetcher(logger),
        max_per_run=None,
    )
    assert queries.updates == [(1, "green")]


@pytest.mark.asyncio
async def test_semaphore_caps_concurrent_fetches(logger):
    """Avec max_concurrent=3, jamais plus de 3 fetches en vol.

    On injecte un fetcher instrumenté, sans passer par le routeur HTTP, pour mesurer la concurrence.
    """
    in_flight = 0
    peak = [0]

    async def tracked_fetcher(client, doi):  # noqa: ARG001
        nonlocal in_flight
        in_flight += 1
        peak[0] = max(peak[0], in_flight)
        try:
            await asyncio.sleep(0.01)  # laisser le scheduler interleaver
            return "green"
        finally:
            in_flight -= 1

    pubs = [(i, f"10.1/{i}", "closed", False) for i in range(10)]
    await module.run(
        MagicMock(),
        _FakeQueries(pubs),
        logger,
        fetcher=tracked_fetcher,
        max_per_run=None,
        max_concurrent=3,
    )
    assert peak[0] == 3
