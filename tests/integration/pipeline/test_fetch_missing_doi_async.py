"""Tests pour `application.pipeline.fetch_missing_doi.run_async`.

Deux angles :
1. **Orchestrateur** : via un fake adapter, vérifie la parallélisation,
   le sémaphore, le lock DB, et la remontée des stats.
2. **Adapter OpenAlex + helper async** : via `respx` (mocks httpx),
   vérifie que `fetch_async` et `http_request_with_retry_async`
   parlent à l'API correctement (happy path, 429 retry, erreur).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from application.pipeline.fetch_missing_doi import run_async
from domain.pipeline_metrics import PhaseMetrics
from infrastructure.sources.hal.fetch_missing_doi import HalFetchMissingDoiAdapter
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.openalex.fetch_missing_doi import OpenalexFetchMissingDoiAdapter
from infrastructure.sources.scanr.fetch_missing_doi import ScanrFetchMissingDoiAdapter
from infrastructure.sources.wos.fetch_missing_doi import WosFetchMissingDoiAdapter

# ── helpers ──────────────────────────────────────────────────────


class _FakeAdapter:
    """Adapter de test : fetch_async mockable, insert qui compte."""

    source_key = "fake"
    batch_size = 1
    max_concurrent = 3

    def __init__(
        self,
        *,
        fetch_result: Iterable[dict] | Exception = (),
        record_in_flight: list[int] | None = None,
    ) -> None:
        self._fetch_result = fetch_result
        self._in_flight = 0
        self.record_in_flight = record_in_flight if record_in_flight is not None else []
        self.inserted_records: list[dict] = []

    def configure(self, conn):  # noqa: ARG002
        pass

    async def fetch_async(self, client, dois):  # noqa: ARG002
        self._in_flight += 1
        self.record_in_flight.append(self._in_flight)
        # Petit await pour permettre au scheduler asyncio d'interleaver
        await asyncio.sleep(0.01)
        self._in_flight -= 1
        if isinstance(self._fetch_result, Exception):
            raise self._fetch_result
        return [{"doi": dois[0]}]

    def insert(self, conn, record):  # noqa: ARG002
        self.inserted_records.append(record)
        return True


def _reader(dois: list[str]):
    """Fabrique un `cross_import_dois_reader` qui retourne une liste fixe."""

    def _read(conn, target, all_staged):  # noqa: ARG001
        return dois

    return _read


# ── orchestrateur : parallélisme + sémaphore + stats ─────────────


class TestRunAsyncOrchestrator:
    @pytest.mark.asyncio
    async def test_happy_path_returns_stats(self):
        adapter = _FakeAdapter()
        result = await run_async(
            MagicMock(),
            adapter,
            logging.getLogger("test"),
            cross_import_dois_reader=_reader(["10.1/a", "10.1/b", "10.1/c"]),
        )
        assert result == PhaseMetrics(total=3, new=3, extras={"fetched": 3})
        assert len(adapter.inserted_records) == 3

    @pytest.mark.asyncio
    async def test_semaphore_caps_concurrent_fetches(self):
        """`max_concurrent=3` doit plafonner à 3 le nb de fetches en vol."""
        in_flight: list[int] = []
        adapter = _FakeAdapter(record_in_flight=in_flight)
        adapter.max_concurrent = 3
        dois = [f"10.1/{i}" for i in range(10)]

        await run_async(
            MagicMock(),
            adapter,
            logging.getLogger("test"),
            cross_import_dois_reader=_reader(dois),
        )
        assert max(in_flight) <= 3
        # Avec 10 DOIs et sem=3, on doit avoir vu le sem saturé au moins une fois
        assert max(in_flight) == 3

    @pytest.mark.asyncio
    async def test_dry_run_skips_fetch(self):
        adapter = _FakeAdapter()
        result = await run_async(
            MagicMock(),
            adapter,
            logging.getLogger("test"),
            cross_import_dois_reader=_reader(["10.1/a", "10.1/b"]),
            dry_run=True,
        )
        assert result == PhaseMetrics(total=2)
        assert adapter.inserted_records == []

    @pytest.mark.asyncio
    async def test_limit_truncates_dois(self):
        adapter = _FakeAdapter()
        result = await run_async(
            MagicMock(),
            adapter,
            logging.getLogger("test"),
            cross_import_dois_reader=_reader([f"10.1/{i}" for i in range(10)]),
            limit=3,
        )
        assert result.total == 3

    @pytest.mark.asyncio
    async def test_empty_dois_returns_zero(self):
        adapter = _FakeAdapter()
        result = await run_async(
            MagicMock(),
            adapter,
            logging.getLogger("test"),
            cross_import_dois_reader=_reader([]),
        )
        assert result == PhaseMetrics()

    @pytest.mark.asyncio
    async def test_fetch_error_continues_other_dois(self):
        """Une exception dans fetch_async sur un lot ne doit pas arrêter les autres."""

        class _FlakyAdapter(_FakeAdapter):
            calls = 0

            async def fetch_async(self, client, dois):
                type(self).calls += 1
                if dois[0] == "10.1/bad":
                    raise RuntimeError("boom")
                return [{"doi": dois[0]}]

        adapter = _FlakyAdapter()
        result = await run_async(
            MagicMock(),
            adapter,
            logging.getLogger("test"),
            cross_import_dois_reader=_reader(["10.1/ok1", "10.1/bad", "10.1/ok2"]),
        )
        assert result.total == 3
        assert result.extras["fetched"] == 2  # seulement les 2 OK
        assert result.new == 2


# ── helper api_retry_async ───────────────────────────────────────


class TestApiRetryAsync:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success_returns_json(self):
        route = respx.get("https://api.example/foo").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        async with httpx.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client, "GET", "https://api.example/foo", label="test"
            )
        assert data == {"ok": True}
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_429_then_succeeds(self):
        route = respx.get("https://api.example/foo").mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        async with httpx.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client,
                "GET",
                "https://api.example/foo",
                initial_backoff=0.01,  # rapide pour les tests
                label="test",
            )
        assert data == {"ok": True}
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_on_persistent_network_error(self):
        respx.get("https://api.example/foo").mock(side_effect=httpx.ConnectError("refused"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.ConnectError):
                await http_request_with_retry_async(
                    client,
                    "GET",
                    "https://api.example/foo",
                    max_retries=2,
                    initial_backoff=0.01,
                    label="test",
                )

    @pytest.mark.asyncio
    @respx.mock
    async def test_retries_on_empty_body_when_enabled(self):
        route = respx.get("https://api.example/foo").mock(
            side_effect=[
                httpx.Response(200, text=""),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        async with httpx.AsyncClient() as client:
            data = await http_request_with_retry_async(
                client,
                "GET",
                "https://api.example/foo",
                retry_on_empty_body=True,
                initial_backoff=0.01,
                label="test",
            )
        assert data == {"ok": True}
        assert route.call_count == 2


# ── adapter OpenAlex : fetch_async via respx ─────────────────────


class TestOpenalexFetchAsync:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_returns_first_result(self):
        respx.get("https://api.openalex.org/works").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1/a"}
                    ]
                },
            )
        )
        adapter = OpenalexFetchMissingDoiAdapter()
        adapter.base_url = "https://api.openalex.org/works"

        async with httpx.AsyncClient() as client:
            records = list(await adapter.fetch_async(client, ["10.1/a"]))
        assert len(records) == 1
        assert records[0]["id"].endswith("W123")

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_no_result_returns_empty(self):
        respx.get("https://api.openalex.org/works").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        adapter = OpenalexFetchMissingDoiAdapter()
        adapter.base_url = "https://api.openalex.org/works"

        async with httpx.AsyncClient() as client:
            records = list(await adapter.fetch_async(client, ["10.1/missing"]))
        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_network_error_returns_empty(self):
        """Erreur réseau persistante → l'adapter retourne [] (comportement
        historique : un DOI qui échoue ne fait pas échouer la boucle)."""
        respx.get("https://api.openalex.org/works").mock(side_effect=httpx.ConnectError("refused"))
        adapter = OpenalexFetchMissingDoiAdapter()
        adapter.base_url = "https://api.openalex.org/works"

        async with httpx.AsyncClient() as client:
            records = list(await adapter.fetch_async(client, ["10.1/net-error"]))
        assert records == []


# ── adapter HAL : fetch_async via respx ──────────────────────────


class TestHalFetchAsync:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_returns_first_doc(self):
        respx.get("https://api.archives-ouvertes.fr/search/").mock(
            return_value=httpx.Response(
                200,
                json={"response": {"docs": [{"halId_s": "hal-00012345", "doiId_s": "10.1/a"}]}},
            )
        )
        adapter = HalFetchMissingDoiAdapter()
        adapter.base_url = "https://api.archives-ouvertes.fr/search/"

        async with httpx.AsyncClient() as client:
            docs = list(await adapter.fetch_async(client, ["10.1/a"]))
        assert len(docs) == 1
        assert docs[0]["halId_s"] == "hal-00012345"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_no_result_returns_empty(self):
        respx.get("https://api.archives-ouvertes.fr/search/").mock(
            return_value=httpx.Response(200, json={"response": {"docs": []}})
        )
        adapter = HalFetchMissingDoiAdapter()
        adapter.base_url = "https://api.archives-ouvertes.fr/search/"

        async with httpx.AsyncClient() as client:
            docs = list(await adapter.fetch_async(client, ["10.1/missing"]))
        assert docs == []


# ── adapter ScanR : fetch_async via respx ────────────────────────


class TestScanrFetchAsync:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_returns_hits_sources(self):
        respx.post("https://scanr.example/_search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "id": "scanr-1",
                                    "externalIds": [{"type": "doi", "id": "10.1/a"}],
                                }
                            }
                        ]
                    }
                },
            )
        )
        adapter = ScanrFetchMissingDoiAdapter()
        adapter.url = "https://scanr.example/_search"
        adapter.auth = ("u", "p")

        async with httpx.AsyncClient() as client:
            records = list(await adapter.fetch_async(client, ["10.1/a"]))
        assert len(records) == 1
        assert records[0]["id"] == "scanr-1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_auth_failure_returns_empty(self):
        """Erreur HTTP (401/403/500...) → [] sans propager l'exception."""
        respx.post("https://scanr.example/_search").mock(return_value=httpx.Response(401))
        adapter = ScanrFetchMissingDoiAdapter()
        adapter.url = "https://scanr.example/_search"
        adapter.auth = ("u", "p")

        async with httpx.AsyncClient() as client:
            records = list(await adapter.fetch_async(client, ["10.1/a"]))
        assert records == []


# ── adapter WoS : fetch_async via respx ──────────────────────────


class TestWosFetchAsync:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_single_page(self):
        """Lot de DOIs qui tient sur une seule page."""
        respx.get("https://api.clarivate.com/api/wos").mock(
            return_value=httpx.Response(
                200,
                json={
                    "QueryResult": {"RecordsFound": 2},
                    "Data": {
                        "Records": {
                            "records": {
                                "REC": [
                                    {"UID": "WOS:001"},
                                    {"UID": "WOS:002"},
                                ]
                            }
                        }
                    },
                },
            )
        )
        adapter = WosFetchMissingDoiAdapter()
        adapter.base_url = "https://api.clarivate.com/api/wos"
        adapter.headers = {"X-ApiKey": "k", "Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            records = list(await adapter.fetch_async(client, ["10.1/a", "10.1/b"]))
        assert [r["UID"] for r in records] == ["WOS:001", "WOS:002"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_400_skips_silently(self):
        """WoS 400 = lot sans correspondance → retourne ce qui a été accumulé,
        sans propager l'exception."""
        respx.get("https://api.clarivate.com/api/wos").mock(return_value=httpx.Response(400))
        adapter = WosFetchMissingDoiAdapter()
        adapter.base_url = "https://api.clarivate.com/api/wos"
        adapter.headers = {"X-ApiKey": "k", "Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            records = list(await adapter.fetch_async(client, ["10.1/a"]))
        assert records == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_async_filters_preprint_dois(self):
        """DOIs Zenodo/arXiv/SSRN sont filtrés avant appel → pas d'appel HTTP
        si le lot entier ne contient que des preprints."""
        route = respx.get("https://api.clarivate.com/api/wos").mock()

        adapter = WosFetchMissingDoiAdapter()
        adapter.base_url = "https://api.clarivate.com/api/wos"
        adapter.headers = {"X-ApiKey": "k", "Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            records = list(
                await adapter.fetch_async(client, ["10.48550/arxiv.1234", "10.5281/zenodo.1"])
            )
        assert records == []
        assert route.call_count == 0
