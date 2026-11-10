"""Tâches asynchrones de la phase `oa_status` (`pipeline.transformation.publications.oa_status`), avec les requêtes d'Unpaywall et de doi.org (`pipeline.ingestion.complements`).

Ce module teste les réponses écrites par DOI, la mise en file de consolidation des publications des DOI dont la réponse change, le DOI absent, le service indisponible, la réponse 429 et le plafond de concurrence. Les règles du statut open access sont testées dans `tests/unit/domain/publications/test_open_access.py`.

Le store est simulé et capture les écritures. Les réponses HTTP viennent de la fixture `http_mock`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx2
import pytest

from pipeline.http.lookup import LookupOutcome
from pipeline.ingestion.api_params import MAX_CONCURRENT
from pipeline.ingestion.complements.doi_org import fetch_registered_url
from pipeline.ingestion.complements.unpaywall import fetch_oa_status
from pipeline.phases import PHASES
from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from pipeline.transformation.publications import oa_status
from pipeline.transformation.publications.oa_status import (
    DOI_ORG,
    UNPAYWALL,
    DoiFetcher,
    DoiLookupTask,
    DoiService,
)

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
HANDLES_BASE = "https://doi.org/api/handles"
TEST_EMAIL = "test@example.com"


def _make_fetcher():
    """Renvoie la requête Unpaywall réelle, sur l'URL et l'adresse de test."""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
        return await fetch_oa_status(client, doi, base_url=UNPAYWALL_BASE, email=TEST_EMAIL)

    return fetcher


async def _doi_org_fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:
    return await fetch_registered_url(client, doi, user_agent="test")


def _answering(answer: str) -> DoiFetcher:
    """Renvoie une requête simulée, qui donne la même réponse pour tout DOI."""

    async def fetcher(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[str]:  # noqa: ARG001
        return answer

    return fetcher


def _handle_route(http_mock, doi: str, *, values: list | None = None, http_status: int = 200):
    """Déclare la réponse de l'API des handles pour un DOI : ses valeurs `values` sous le code `http_status`."""
    return http_mock.get(f"{HANDLES_BASE}/{doi}").mock(
        return_value=httpx2.Response(http_status, json={"responseCode": 1, "values": values or []})
    )


def _route(http_mock, doi: str, *, status: str | None = None, http_status: int = 200):
    """Déclare la réponse Unpaywall pour un DOI : le statut `status` (`'gold'`, `'closed'`…) sous le code `http_status`, ou un corps vide quand `status` vaut `None`."""
    body = {"oa_status": status} if status is not None else None
    return http_mock.get(f"{UNPAYWALL_BASE}/{doi}").mock(
        return_value=httpx2.Response(http_status, json=body)
    )


class _FakeStore:
    """DOI à interroger, réponses en table, et capture des écritures (`record_answers`) et des mises en file (`enqueue_publications`). Chaque DOI a une publication."""

    def __init__(
        self,
        dois: list[str],
        *,
        stale_total: int | None = None,
        stored: dict[str, str | None] | None = None,
    ) -> None:
        self._dois = dois
        self._stale_total = stale_total if stale_total is not None else len(dois)
        self._stored = stored or {}
        self.answers: list[tuple[str, str | None]] = []
        self.services: set[DoiService] = set()
        self.enqueued: list[str] = []

    def fetch_answers(self, service, dois) -> dict[str, str | None]:  # noqa: ARG002
        return {d: s for d, s in self._stored.items() if d in set(dois)}

    def fetch_dois_to_query(self, service, *, limit=None, staleness_days):  # noqa: ARG002
        return self._dois[:limit] if limit else self._dois

    def count_dois_to_query(self, service, *, staleness_days) -> int:  # noqa: ARG002
        return self._stale_total

    def record_answers(self, service, answers) -> None:
        self.services.add(service)
        self.answers.extend(answers)

    def enqueue_publications(self, dois) -> int:
        self.enqueued.extend(dois)
        return len(dois)


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_enrich_oa_status")


@contextmanager
def _open_tx():
    yield MagicMock()


def _task(
    queries: _FakeStore,
    fetcher: DoiFetcher,
    *,
    service: DoiService = UNPAYWALL,
    max_concurrent: int = MAX_CONCURRENT["unpaywall"],
) -> DoiLookupTask:
    """Construit une tâche sans plafond par run, sur le store simulé."""
    return DoiLookupTask(
        service,
        fetcher,
        participle="vérifié",
        not_found=("non trouvé", "non trouvés"),
        staleness_days=lambda conn: 15,  # noqa: ARG005
        max_per_run=lambda conn: None,  # noqa: ARG005
        max_concurrent=max_concurrent,
        store_factory=lambda conn: queries,  # noqa: ARG005
    )


def _context(logger: logging.Logger, **overrides) -> PhaseContext:
    """Contexte sur une transaction inerte, sources configurées."""
    return PhaseContext(
        **{
            "open_tx": _open_tx,
            "logger": logger,
            "options": RunOptions(),
            "maintain": lambda op: None,
            "credentials_missing": lambda _source: None,
            "request_budget": lambda _source: None,
            **overrides,
        }
    )


def _run(
    queries: _FakeStore,
    fetcher: DoiFetcher,
    logger: logging.Logger,
    *,
    service: DoiService = UNPAYWALL,
    max_concurrent: int = MAX_CONCURRENT["unpaywall"],
) -> PhaseMetrics:
    """Exécute une tâche sur une transaction inerte."""
    task = _task(queries, fetcher, service=service, max_concurrent=max_concurrent)
    return task.run(_context(logger))


def test_les_reponses_changees_mettent_leurs_publications_en_file(logger, http_mock):
    _route(http_mock, "10.1/a", status="gold")
    _route(http_mock, "10.1/b", status="green")
    _route(http_mock, "10.1/c", status="bronze")

    queries = _FakeStore(
        ["10.1/a", "10.1/b", "10.1/c"],
        stale_total=42,
        stored={"10.1/b": "closed", "10.1/c": "bronze"},
    )
    metrics = oa_status.assemble({"verify_unpaywall": _run(queries, _make_fetcher(), logger)})

    assert sorted(queries.answers) == [
        ("10.1/a", "gold"),
        ("10.1/b", "green"),
        ("10.1/c", "bronze"),
    ]
    # 10.1/a nouveau et 10.1/b modifié entrent en file ; 10.1/c inchangé reste hors file.
    assert sorted(queries.enqueued) == ["10.1/a", "10.1/b"]
    assert (metrics.total, metrics.new, metrics.updated, metrics.unchanged) == (3, 1, 1, 1)
    assert metrics.extras["not_found"] == 0
    [service] = metrics.details["services"]["rows"]
    assert service["key"] == "verify_unpaywall"
    assert (service["stale"], service["checked"]) == (42, 3)
    assert (service["new"], service["updated"], service["unchanged"]) == (1, 1, 1)


def test_les_deux_services_ont_chacun_leur_ligne(logger):
    resolution, unpaywall = oa_status.TASKS
    phase = dataclasses.replace(
        next(p for p in PHASES if p.name == "oa_status"),
        children=(
            dataclasses.replace(
                resolution,
                run=_task(
                    _FakeStore(["10.1/a"]), _answering("https://example.org/a"), service=DOI_ORG
                ).run,
            ),
            dataclasses.replace(
                unpaywall, run=_task(_FakeStore(["10.1/b"]), _answering("gold")).run
            ),
        ),
    )

    metrics = run_phase(phase, _context(logger))

    assert [row["key"] for row in metrics.details["services"]["rows"]] == [
        "resolve_dois",
        "verify_unpaywall",
    ]


def test_404_ecrit_un_verdict_nul_et_met_la_publication_en_file(logger, http_mock):
    _route(http_mock, "10.1/x", http_status=404)

    queries = _FakeStore(["10.1/x"], stored={"10.1/x": "closed"})
    metrics = _run(queries, _make_fetcher(), logger)
    assert queries.answers == [("10.1/x", None)]
    assert queries.enqueued == ["10.1/x"]
    assert (metrics.extras["not_found"], metrics.updated) == (1, 0)


def test_unavailable_leaves_doi_unchecked(logger, http_mock):
    """Unpaywall indisponible : aucun verdict, le DOI reste à interroger, rien n'entre en file."""
    _route(http_mock, "10.1/x", http_status=403)

    queries = _FakeStore(["10.1/x"])
    metrics = _run(queries, _make_fetcher(), logger)
    assert queries.answers == []
    assert queries.enqueued == []
    assert metrics.errors == 1
    assert metrics.extras["not_found"] == 0


def test_un_verdict_identique_compte_inchange(logger, http_mock):
    _route(http_mock, "10.1/same", status="gold")

    queries = _FakeStore(["10.1/same"], stored={"10.1/same": "gold"})
    metrics = _run(queries, _make_fetcher(), logger)
    assert queries.answers == [("10.1/same", "gold")]
    assert queries.enqueued == []
    assert (metrics.new, metrics.unchanged) == (0, 1)


def test_429_retries_transparently(logger, http_mock):
    """Après une réponse 429, la requête est relancée et la réponse 200 suivante est prise en compte."""
    http_mock.get(f"{UNPAYWALL_BASE}/10.1/r").mock(
        side_effect=[
            httpx2.Response(429),
            httpx2.Response(200, json={"oa_status": "green"}),
        ]
    )

    queries = _FakeStore(["10.1/r"])
    _run(queries, _make_fetcher(), logger)
    assert queries.answers == [("10.1/r", "green")]


def test_semaphore_caps_concurrent_fetches(logger):
    """Avec `max_concurrent=3`, au plus trois requêtes sont en cours à la fois. Une requête simulée compte les requêtes en cours."""
    in_flight = 0
    peak = [0]

    async def tracked_fetcher(client, doi):  # noqa: ARG001
        nonlocal in_flight
        in_flight += 1
        peak[0] = max(peak[0], in_flight)
        try:
            await asyncio.sleep(0.01)  # laisse les autres requêtes démarrer
            return "green"
        finally:
            in_flight -= 1

    _run(_FakeStore([f"10.1/{i}" for i in range(10)]), tracked_fetcher, logger, max_concurrent=3)
    assert peak[0] == 3


def test_skips_without_unpaywall_configuration(logger):
    """Sans configuration Unpaywall, l'accès à la source signale son absence et la tâche s'arrête avant toute transaction."""
    unconfigured = _FakeStore(["10.1/a"])
    open_tx = MagicMock(side_effect=_open_tx)
    resolution, unpaywall = oa_status.TASKS
    phase = dataclasses.replace(
        next(p for p in PHASES if p.name == "oa_status"),
        children=(
            dataclasses.replace(
                resolution, run=_task(_FakeStore([]), _doi_org_fetcher, service=DOI_ORG).run
            ),
            dataclasses.replace(unpaywall, run=_task(unconfigured, _make_fetcher()).run),
        ),
    )

    metrics = run_phase(
        phase,
        _context(
            logger,
            open_tx=open_tx,
            credentials_missing=lambda source: (
                "adresse polite pool absente" if source == "unpaywall" else None
            ),
        ),
    )

    open_tx.assert_called_once()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
    assert unconfigured.answers == []


def test_adresse_enregistree_lue_chez_doi_org(logger, http_mock):
    """La valeur `URL` du handle est écrite ; un DOI inconnu et un handle sans URL reçoivent une URL nulle."""
    _handle_route(
        http_mock,
        "10.1/u",
        values=[
            {
                "index": 1,
                "type": "URL",
                "data": {"format": "string", "value": "https://e.org/a.pdf"},
            }
        ],
    )
    _handle_route(http_mock, "10.1/x", http_status=404)
    _handle_route(http_mock, "10.1/e", values=[])

    queries = _FakeStore(["10.1/u", "10.1/x", "10.1/e"])
    metrics = _run(queries, _doi_org_fetcher, logger, service=DOI_ORG)

    assert queries.services == {DOI_ORG}
    assert sorted(queries.answers) == [
        ("10.1/e", None),
        ("10.1/u", "https://e.org/a.pdf"),
        ("10.1/x", None),
    ]
    assert (metrics.new, metrics.extras["not_found"]) == (1, 2)
