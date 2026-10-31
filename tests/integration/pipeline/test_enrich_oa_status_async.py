"""Tâches asynchrones de la phase `oa_status` (`pipeline.transformation.publications.oa_status`), avec les requêtes d'Unpaywall et de doi.org (`pipeline.ingestion.complements`).

Les règles du statut sont testées dans `tests/unit/domain/publications/test_open_access.py` (`publication_oa_status`). Ce module teste les réponses écrites par DOI, le recalcul des publications de ces DOI, le DOI absent, le service indisponible, la réponse 429 et le plafond de concurrence.

Le store est simulé et capture les écritures. Les réponses HTTP viennent de la fixture `http_mock`.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx2
import pytest

from domain.platforms.platform import PlatformType
from domain.publications.access import Copy
from domain.publications.licenses import License
from pipeline.http.lookup import LookupOutcome
from pipeline.ingestion.complements.doi_org import fetch_registered_url
from pipeline.ingestion.complements.unpaywall import fetch_oa_status
from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.oa_status import (
    DOI_ORG,
    MAX_CONCURRENT,
    UNPAYWALL,
    DoiFetcher,
    DoiLookupTask,
    DoiService,
    OaStatusPhase,
    PublicationOaInputs,
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


def _copy(url: str, *, platform_type: PlatformType | None = None) -> Copy:
    """Construit une copie ouverte sous licence CC BY."""
    return Copy(
        url=url,
        version=None,
        is_oa=True,
        platform=None,
        known_platform=None,
        platform_type=platform_type,
        license=License.CC_BY,
        embargoed=False,
        described_by_platform=False,
        arrival=1,
    )


def _publication(
    publication_id: int, doi: str, current: str | None, *copies: Copy
) -> PublicationOaInputs:
    """Construit la publication d'un DOI, de statut `current`, dans une revue `full_oa`, sans embargo, avec ses `copies`."""
    return PublicationOaInputs(
        publication_id,
        doi,
        current,
        True,
        "full_oa",
        False,
        False,
        None,
        list(copies),
    )


class _FakeStore:
    """DOI à interroger, publications de ces DOI, et capture des écritures (`record_answers`, `update_oa_status`). Une publication lue après l'écriture d'un verdict d'Unpaywall contient ce verdict."""

    def __init__(
        self,
        publications: list[PublicationOaInputs],
        *,
        stale_total: int | None = None,
        oa_distribution: dict[str, int] | None = None,
        stored: dict[str, str | None] | None = None,
    ) -> None:
        self._publications = publications
        self._dois = list(dict.fromkeys(p.doi for p in publications))
        self._stale_total = stale_total if stale_total is not None else len(self._dois)
        self._oa_distribution = oa_distribution or {}
        self._stored = stored or {}
        self.answers: list[tuple[str, str | None]] = []
        self.services: set[DoiService] = set()
        self.updates: list[tuple[int, str]] = []

    def fetch_answers(self, service, dois) -> dict[str, str | None]:  # noqa: ARG002
        return {d: s for d, s in self._stored.items() if d in set(dois)}

    def fetch_dois_to_query(self, service, *, limit=None, staleness_days):  # noqa: ARG002
        return self._dois[:limit] if limit else self._dois

    def count_dois_to_query(self, service, *, staleness_days) -> int:  # noqa: ARG002
        return self._stale_total

    def count_publications_by_oa_status(self) -> dict[str, int]:
        return dict(self._oa_distribution)

    def record_answers(self, service, answers) -> None:
        self.services.add(service)
        self.answers.extend(answers)

    def fetch_oa_inputs(self, dois) -> list[PublicationOaInputs]:
        verdicts = dict(self.answers) if UNPAYWALL in self.services else {}
        return [
            p._replace(unpaywall=verdicts.get(p.doi, p.unpaywall))
            for p in self._publications
            if p.doi in set(dois)
        ]

    def update_oa_status(self, publication_id: int, status: str) -> None:
        self.updates.append((publication_id, status))


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
    max_concurrent: int = MAX_CONCURRENT,
) -> DoiLookupTask:
    """Construit une tâche sans plafond par run, sur le store simulé."""
    return DoiLookupTask(
        service,
        fetcher,
        title="Vérification",
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
    max_concurrent: int = MAX_CONCURRENT,
) -> PhaseMetrics:
    """Exécute une tâche sur une transaction inerte."""
    task = _task(queries, fetcher, service=service, max_concurrent=max_concurrent)
    return task.run(_context(logger))


def test_happy_path_updates_each_publication(logger, http_mock):
    publications = [
        _publication(1, "10.1/a", "closed"),
        _publication(2, "10.1/b", None),
        _publication(3, "10.1/c", "bronze"),
    ]
    _route(http_mock, "10.1/a", status="gold")
    _route(http_mock, "10.1/b", status="green")
    _route(http_mock, "10.1/c", status="bronze")

    queries = _FakeStore(
        publications,
        stale_total=42,
        oa_distribution={"gold": 7, "closed": 3},
        stored={"10.1/b": "closed", "10.1/c": "bronze"},
    )
    metrics = _run(queries, _make_fetcher(), logger)

    assert sorted(queries.answers) == [
        ("10.1/a", "gold"),
        ("10.1/b", "green"),
        ("10.1/c", "bronze"),
    ]
    assert sorted(queries.updates) == [(1, "gold"), (2, "green")]
    # Verdicts : 10.1/a nouveau, 10.1/b modifié, 10.1/c inchangé.
    assert (metrics.total, metrics.new, metrics.updated, metrics.unchanged) == (3, 1, 1, 1)
    assert metrics.extras["not_found"] == 0
    assert "stale" not in metrics.extras
    summary = metrics.details["summary"]
    assert summary["stale"] == 42
    assert summary["checked"] == 3
    assert (summary["new"], summary["updated"], summary["unchanged"]) == (1, 1, 1)
    # Le store simulé renvoie la même distribution avant et après : écart nul, lignes triées par effectif.
    assert metrics.details["table"]["rows"][0] == {"key": "gold", "count": 7, "delta": 0}


def test_404_ecrit_un_verdict_nul_et_le_statut_suit_les_copies(logger, http_mock):
    publications = [_publication(1, "10.1/x", "closed", _copy("https://doi.org/10.1/x"))]
    _route(http_mock, "10.1/x", http_status=404)

    queries = _FakeStore(publications, stored={"10.1/x": "closed"})
    metrics = _run(queries, _make_fetcher(), logger)
    assert queries.answers == [("10.1/x", None)]
    assert queries.updates == [(1, "gold")]
    assert (metrics.extras["not_found"], metrics.updated) == (1, 0)


def test_unavailable_leaves_doi_unchecked(logger, http_mock):
    """Unpaywall indisponible : aucun verdict, le DOI reste dans la file."""
    publications = [_publication(1, "10.1/x", "closed")]
    _route(http_mock, "10.1/x", http_status=403)

    queries = _FakeStore(publications)
    metrics = _run(queries, _make_fetcher(), logger)
    assert queries.answers == []
    assert queries.updates == []
    assert metrics.errors == 1
    assert metrics.extras["not_found"] == 0


def test_le_verdict_n_abaisse_pas_le_statut_des_copies(logger, http_mock):
    """Une copie d'archive ouverte l'emporte sur le statut `closed` d'Unpaywall : la publication reste `green`."""
    publications = [
        _publication(
            1,
            "10.1/deposit",
            "green",
            _copy("https://hal.science/hal-01607327", platform_type=PlatformType.REPOSITORY),
        )
    ]
    _route(http_mock, "10.1/deposit", status="closed")

    queries = _FakeStore(publications)
    _run(queries, _make_fetcher(), logger)
    assert queries.answers == [("10.1/deposit", "closed")]
    assert queries.updates == []


def test_un_verdict_identique_compte_inchange(logger, http_mock):
    publications = [_publication(1, "10.1/same", "gold")]
    _route(http_mock, "10.1/same", status="gold")

    queries = _FakeStore(publications, stored={"10.1/same": "gold"})
    metrics = _run(queries, _make_fetcher(), logger)
    assert queries.answers == [("10.1/same", "gold")]
    assert queries.updates == []
    assert (metrics.new, metrics.unchanged) == (0, 1)


def test_le_bilan_du_journal_classe_les_verdicts(logger, http_mock, caplog):
    publications = [
        _publication(1, "10.1/n", "closed"),
        _publication(2, "10.1/m", "closed"),
        _publication(3, "10.1/x", "closed"),
    ]
    _route(http_mock, "10.1/n", status="gold")
    _route(http_mock, "10.1/m", status="green")
    _route(http_mock, "10.1/x", http_status=404)

    with caplog.at_level(logging.INFO):
        _run(_FakeStore(publications, stored={"10.1/m": "closed"}), _make_fetcher(), logger)

    assert "1 nouveau, 1 modifié, 0 inchangé, 1 non trouvé" in caplog.text


def test_429_retries_transparently(logger, http_mock):
    """Après une réponse 429, la requête est relancée et la réponse 200 suivante est prise en compte."""
    http_mock.get(f"{UNPAYWALL_BASE}/10.1/r").mock(
        side_effect=[
            httpx2.Response(429),
            httpx2.Response(200, json={"oa_status": "green"}),
        ]
    )

    queries = _FakeStore([_publication(1, "10.1/r", "closed")])
    _run(queries, _make_fetcher(), logger)
    assert queries.updates == [(1, "green")]


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

    publications = [_publication(i, f"10.1/{i}", "closed") for i in range(10)]
    _run(_FakeStore(publications), tracked_fetcher, logger, max_concurrent=3)
    assert peak[0] == 3


def test_skips_without_unpaywall_configuration(logger):
    """Sans configuration Unpaywall, l'accès à la source signale son absence et la tâche s'arrête avant toute transaction."""
    queries = _FakeStore([])
    unconfigured = _FakeStore([_publication(1, "10.1/a", "closed")])
    open_tx = MagicMock(side_effect=_open_tx)
    phase = OaStatusPhase(
        resolution=_task(queries, _doi_org_fetcher, service=DOI_ORG),
        unpaywall=_task(unconfigured, _make_fetcher()),
    )

    metrics = phase.run(
        _context(
            logger,
            open_tx=open_tx,
            credentials_missing=lambda source: (
                "adresse polite pool absente" if source == "unpaywall" else None
            ),
        )
    )

    open_tx.assert_called_once()
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]
    assert unconfigured.answers == []


def test_adresse_enregistree_lue_chez_doi_org(logger, http_mock):
    """La valeur `URL` du handle est écrite ; un DOI inconnu et un handle sans adresse reçoivent une adresse nulle."""
    publications = [
        _publication(1, "10.1/u", None),
        _publication(2, "10.1/x", None),
        _publication(3, "10.1/e", None),
    ]
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

    queries = _FakeStore(publications)
    metrics = _run(queries, _doi_org_fetcher, logger, service=DOI_ORG)

    assert queries.services == {DOI_ORG}
    assert sorted(queries.answers) == [
        ("10.1/e", None),
        ("10.1/u", "https://e.org/a.pdf"),
        ("10.1/x", None),
    ]
    assert (metrics.new, metrics.extras["not_found"]) == (1, 2)
