"""Recherche par DOI de la phase `fetch_missing` (`pipeline.ingestion.common.doi_search.fetch_missing_doi`).

Deux angles :
1. **Boucle** : via une fausse recherche, vérifie le pool de workers, l'inscription des DOI absents et les métriques.
2. **Recherches par source** : via la fixture `http_mock`, vérifie que `fetch_async` parle à l'API correctement (enregistrement source trouvé, absence, erreurs réseau et HTTP).
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import httpx2
import pytest

from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common import doi_search
from pipeline.ingestion.common.doi_search import DoiBatchResult, fetch_missing_doi
from pipeline.ingestion.common.staging import StagingStore, UpsertOutcome
from pipeline.ingestion.complements.doi_org import doi_existence
from pipeline.ingestion.crossref.fetch_missing import CrossrefDoiSearch
from pipeline.ingestion.datacite.fetch_missing import DataciteDoiSearch
from pipeline.ingestion.hal.fetch_missing import HalDoiSearch
from pipeline.ingestion.openalex.fetch_missing import OpenalexDoiSearch
from pipeline.ingestion.scanr.fetch_missing import ScanrDoiSearch
from pipeline.ingestion.wos.fetch_missing import WosDoiSearch
from pipeline.runtime.observability.metrics import PhaseMetrics

# ── helpers ──────────────────────────────────────────────────────


def _sans_config[S](cls: type[S], **attributs: object) -> S:
    """Recherche `cls` construite sans lire la configuration, avec les attributs donnés."""
    search = cls.__new__(cls)
    for nom, valeur in attributs.items():
        setattr(search, nom, valeur)
    return search


class _FakeAdapter:
    """Recherche de test : rend un enregistrement source par DOI, sauf les DOI de `absents` ; `inserted_records` retient les écritures."""

    source_key = "openalex"
    batch_size = 1
    max_concurrent = 3
    request_delay_s = 0.0

    def __init__(
        self,
        *,
        absents: frozenset[str] = frozenset(),
        record_in_flight: list[int] | None = None,
    ) -> None:
        self._absents = absents
        self._in_flight = 0
        self.record_in_flight = record_in_flight if record_in_flight is not None else []
        self.inserted_records: list[dict] = []

    async def fetch_async(self, client, dois):  # noqa: ARG002
        self._in_flight += 1
        self.record_in_flight.append(self._in_flight)
        # Petit await pour permettre au scheduler asyncio d'interleaver
        await asyncio.sleep(0.01)
        self._in_flight -= 1
        if dois[0] in self._absents:
            return DoiBatchResult(not_found=[dois[0]])
        return DoiBatchResult(records=[{"doi": dois[0]}])


async def _run(adapter, dois: list[str], *, recorded: list | None = None, **kw) -> PhaseMetrics:
    """`fetch_missing_doi` sur une connexion simulée et la sélection `dois` ; les DOI inscrits absents s'ajoutent à `recorded`."""

    def _record(conn, source, id_type, doi):  # noqa: ARG001
        if recorded is not None:
            recorded.append((source, doi))

    def _stage(_store, source, record, *, entry_mode, listed=True):  # noqa: ARG001
        adapter.inserted_records.append(record)
        return UpsertOutcome.NEW

    with (
        patch.object(
            doi_search, "get_missing_dois", lambda conn, target, *, retry_after_days: dois
        ),
        patch.object(doi_search, "record_failed_lookup", _record),
        patch.object(StagingStore, "stage", _stage),
    ):
        return await fetch_missing_doi(
            MagicMock(), adapter, logging.getLogger("test"), retry_after_days=30, **kw
        )


# ── orchestrateur : parallélisme + sémaphore + stats ─────────────


class TestRunAsyncOrchestrator:
    @pytest.mark.asyncio
    async def test_happy_path_returns_stats(self):
        adapter = _FakeAdapter()
        result = await _run(adapter, ["10.1/a", "10.1/b", "10.1/c"])
        assert result == PhaseMetrics(
            seen=3, new=3, extras={"fetched": 3, "not_found": 0, "unknown_to_doi_org": 0}
        )
        assert len(adapter.inserted_records) == 3

    @pytest.mark.asyncio
    async def test_absent_dois_are_recorded(self):
        """Un DOI dont la source confirme l'absence est inscrit dans `failed_lookups`, sans insertion."""
        recorded: list = []
        adapter = _FakeAdapter(absents=frozenset({"10.1/b"}))
        result = await _run(adapter, ["10.1/a", "10.1/b"], recorded=recorded)
        assert recorded == [("openalex", "10.1/b")]
        assert result.extras == {"fetched": 1, "not_found": 1, "unknown_to_doi_org": 0}
        assert adapter.inserted_records == [{"doi": "10.1/a"}]

    @pytest.mark.asyncio
    async def test_l_agence_d_enregistrement_soumet_ses_absents_a_doi_org(self):
        """Un DOI absent de son agence d'enregistrement est soumis à doi.org ; seul celui que doi.org ne connaît pas est inscrit sous `doi_org`."""
        recorded: list = []
        adapter = _FakeAdapter(absents=frozenset({"10.1/connu", "10.1/inconnu"}))
        adapter.source_key = "crossref"

        async def _existence(client, dois, *, user_agent):  # noqa: ARG001
            return [d for d in dois if d == "10.1/connu"], [d for d in dois if d == "10.1/inconnu"]

        with (
            patch.object(doi_search, "doi_existence", _existence),
            patch.object(doi_search, "polite_user_agent", lambda: "test"),
        ):
            result = await _run(adapter, ["10.1/connu", "10.1/inconnu"], recorded=recorded)

        assert sorted(recorded) == [
            ("crossref", "10.1/connu"),
            ("crossref", "10.1/inconnu"),
            ("doi_org", "10.1/inconnu"),
        ]
        assert result.extras["unknown_to_doi_org"] == 1

    @pytest.mark.asyncio
    async def test_worker_pool_caps_concurrent_fetches(self):
        """`max_concurrent=3` workers doivent plafonner à 3 le nb de fetches en vol."""
        in_flight: list[int] = []
        adapter = _FakeAdapter(record_in_flight=in_flight)
        adapter.max_concurrent = 3
        await _run(adapter, [f"10.1/{i}" for i in range(10)])
        assert max(in_flight) <= 3
        # Avec 10 DOIs et 3 workers, on doit avoir vu les 3 workers saturés au moins une fois
        assert max(in_flight) == 3

    @pytest.mark.asyncio
    async def test_limit_truncates_dois(self):
        result = await _run(_FakeAdapter(), [f"10.1/{i}" for i in range(10)], limit=3)
        assert result.total == 3

    @pytest.mark.asyncio
    async def test_empty_dois_returns_zero(self):
        result = await _run(_FakeAdapter(), [])
        assert result == PhaseMetrics()

    @pytest.mark.asyncio
    async def test_fetch_error_continues_other_dois(self):
        """Une exception dans fetch_async sur un lot ne doit pas arrêter les autres."""

        class _FlakyAdapter(_FakeAdapter):
            async def fetch_async(self, client, dois):
                if dois[0] == "10.1/bad":
                    raise RuntimeError("boom")
                return DoiBatchResult(records=[{"doi": dois[0]}])

        result = await _run(_FlakyAdapter(), ["10.1/ok1", "10.1/bad", "10.1/ok2"])
        assert result.total == 3
        assert result.extras["fetched"] == 2  # seulement les 2 OK
        assert result.new == 2


# ── recherche OpenAlex : fetch_async via http_mock ─────────────────


class TestOpenalexFetchAsync:
    @staticmethod
    def _adapter() -> OpenalexDoiSearch:
        return _sans_config(OpenalexDoiSearch, base_url="https://api.openalex.org/works")

    @pytest.mark.asyncio
    async def test_fetch_async_returns_first_result(self, http_mock):
        http_mock.get("https://api.openalex.org/works").mock(
            return_value=httpx2.Response(
                200,
                json={
                    "results": [
                        {"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1/a"}
                    ]
                },
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert len(result.records) == 1
        assert result.records[0]["id"].endswith("W123")
        assert result.not_found == []

    @pytest.mark.asyncio
    async def test_fetch_async_no_result_is_not_found(self, http_mock):
        """Réponse valide sans résultat → DOI confirmé absent."""
        http_mock.get("https://api.openalex.org/works").mock(
            return_value=httpx2.Response(200, json={"results": []})
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/missing"])
        assert result == DoiBatchResult(not_found=["10.1/missing"])

    @pytest.mark.asyncio
    async def test_fetch_async_network_error_concludes_nothing(self, http_mock):
        """Erreur réseau persistante → ni enregistrement source ni absence : le DOI attend le run suivant."""
        http_mock.get("https://api.openalex.org/works").mock(
            side_effect=httpx2.ConnectError("refused")
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/net-error"])
        assert result == DoiBatchResult()

    @pytest.mark.asyncio
    async def test_fetch_async_http_error_concludes_nothing(self, http_mock):
        """Erreur HTTP (401/4xx/5xx), y compris 404 de l'endpoint de recherche → ni enregistrement source ni absence."""
        http_mock.get("https://api.openalex.org/works").mock(return_value=httpx2.Response(404))
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert result == DoiBatchResult()


# ── recherche HAL : fetch_async via http_mock ──────────────────────


class TestHalFetchAsync:
    @staticmethod
    def _adapter() -> HalDoiSearch:
        return HalDoiSearch()

    @pytest.mark.asyncio
    async def test_fetch_async_returns_first_doc(self, http_mock):
        http_mock.get("https://api.archives-ouvertes.fr/search/").mock(
            return_value=httpx2.Response(
                200,
                json={"response": {"docs": [{"halId_s": "hal-00012345", "doiId_s": "10.1/a"}]}},
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert [d["halId_s"] for d in result.records] == ["hal-00012345"]

    @pytest.mark.asyncio
    async def test_fetch_async_no_result_is_not_found(self, http_mock):
        """Réponse Solr valide sans doc → DOI confirmé absent."""
        http_mock.get("https://api.archives-ouvertes.fr/search/").mock(
            return_value=httpx2.Response(200, json={"response": {"docs": []}})
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/missing"])
        assert result == DoiBatchResult(not_found=["10.1/missing"])


# ── recherche Crossref : fetch_async via http_mock ─────────────────


class TestCrossrefFetchAsync:
    @staticmethod
    def _adapter() -> CrossrefDoiSearch:
        return _sans_config(CrossrefDoiSearch, base_url="https://api.crossref.org", headers={})

    @pytest.mark.asyncio
    async def test_un_doi_principal_rend_son_document(self, http_mock):
        http_mock.get("https://api.crossref.org/works/10.1/a").mock(
            return_value=httpx2.Response(200, json={"message": {"DOI": "10.1/A"}})
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert result == DoiBatchResult(records=[{"DOI": "10.1/A"}])

    @pytest.mark.asyncio
    async def test_un_404_est_une_absence(self, http_mock):
        http_mock.get("https://api.crossref.org/works/10.1/x").mock(
            return_value=httpx2.Response(404)
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/x"])
        assert result == DoiBatchResult(not_found=["10.1/x"])

    @pytest.mark.asyncio
    async def test_un_doi_alias_rend_le_document_principal_et_une_absence(self, http_mock):
        """Crossref redirige un alias vers son DOI principal : le document principal entre, l'alias est inscrit comme introuvable."""
        http_mock.get("https://api.crossref.org/works/10.1/alias").mock(
            return_value=httpx2.Response(301, headers={"location": "/works/10.1/principal"})
        )
        http_mock.get("https://api.crossref.org/works/10.1/principal").mock(
            return_value=httpx2.Response(200, json={"message": {"DOI": "10.1/PRINCIPAL"}})
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/alias"])
        assert result == DoiBatchResult(
            records=[{"DOI": "10.1/PRINCIPAL"}], not_found=["10.1/alias"]
        )


# ── recherche ScanR : fetch_async via http_mock ────────────────────


def _scanr_hit(scanr_id: str, doi: str) -> dict:
    return {"_source": {"id": scanr_id, "externalIds": [{"type": "doi", "id": doi}]}}


class TestScanrFetchAsync:
    @staticmethod
    def _adapter() -> ScanrDoiSearch:
        return ScanrDoiSearch()

    @pytest.mark.asyncio
    async def test_fetch_async_returns_hits_sources(self, http_mock):
        http_mock.post(API_BASE_URLS["scanr"]).mock(
            return_value=httpx2.Response(
                200, json={"hits": {"hits": [_scanr_hit("scanr-1", "10.1/a")]}}
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert [r["id"] for r in result.records] == ["scanr-1"]
        assert result.not_found == []

    @pytest.mark.asyncio
    async def test_fetch_async_batch_marks_unmatched_dois(self, http_mock):
        """Lot de 2 DOI, un seul hit : le DOI sans correspondance est confirmé absent (diff requêtés / trouvés)."""
        http_mock.post(API_BASE_URLS["scanr"]).mock(
            return_value=httpx2.Response(
                200, json={"hits": {"hits": [_scanr_hit("scanr-1", "10.1/a")]}}
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a", "10.1/b"])
        assert [r["id"] for r in result.records] == ["scanr-1"]
        assert result.not_found == ["10.1/b"]

    @pytest.mark.asyncio
    async def test_fetch_async_auth_failure_concludes_nothing(self, http_mock):
        """Erreur HTTP (401/403/500...) → ni enregistrement source ni absence, sans propager l'exception."""
        http_mock.post(API_BASE_URLS["scanr"]).mock(return_value=httpx2.Response(401))
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert result == DoiBatchResult()


# ── recherche DataCite : fetch_async (batch query) via http_mock ───


class TestDoiOrgExistence:
    @pytest.mark.asyncio
    async def test_range_les_doi_selon_doi_org(self, http_mock):
        """200 : doi.org connaît le DOI ; 404 : il ne le connaît pas ; 503 : pas de conclusion."""
        base = API_BASE_URLS["doi_org_handles"]
        http_mock.get(f"{base}/10.1/connu").mock(
            return_value=httpx2.Response(200, json={"responseCode": 1})
        )
        http_mock.get(f"{base}/10.1/inconnu").mock(
            return_value=httpx2.Response(404, json={"responseCode": 100})
        )
        http_mock.get(f"{base}/10.1/muet").mock(return_value=httpx2.Response(503))
        async with httpx2.AsyncClient() as client:
            known, unknown = await doi_existence(
                client, ["10.1/connu", "10.1/inconnu", "10.1/muet"], user_agent="test"
            )
        assert (known, unknown) == (["10.1/connu"], ["10.1/inconnu"])


class TestDataciteFetchAsync:
    @staticmethod
    def _adapter() -> DataciteDoiSearch:
        return _sans_config(
            DataciteDoiSearch,
            base_url="https://api.datacite.org",
            headers={"Accept": "application/vnd.api+json"},
        )

    @pytest.mark.asyncio
    async def test_fetch_async_batch_returns_records(self, http_mock):
        """Lot de 2 DOI, 2 nœuds `data` : remappés par DOI exact (lowercase)."""
        http_mock.get("https://api.datacite.org/dois").mock(
            return_value=httpx2.Response(
                200,
                json={
                    "data": [
                        {"id": "10.1/A", "attributes": {"doi": "10.1/A"}},
                        {"id": "10.1/B", "attributes": {"doi": "10.1/B"}},
                    ]
                },
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a", "10.1/b"])
        assert result.not_found == []
        assert {r["attributes"]["doi"] for r in result.records} == {"10.1/A", "10.1/B"}

    @pytest.mark.asyncio
    async def test_fetch_async_batch_marks_unmatched_dois(self, http_mock):
        """Lot de 2 DOI, un seul nœud : le DOI absent de la réponse est confirmé absent (diff requêtés / trouvés)."""
        http_mock.get("https://api.datacite.org/dois").mock(
            return_value=httpx2.Response(
                200, json={"data": [{"id": "10.1/a", "attributes": {"doi": "10.1/a"}}]}
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a", "10.1/b"])
        assert [r["attributes"]["doi"] for r in result.records] == ["10.1/a"]
        assert result.not_found == ["10.1/b"]

    @pytest.mark.asyncio
    async def test_fetch_async_network_error_concludes_nothing(self, http_mock):
        """Erreur réseau persistante = lot incomplet : aucun DOI n'est déclaré absent."""
        http_mock.get("https://api.datacite.org/dois").mock(
            side_effect=httpx2.ConnectError("refused")
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert result == DoiBatchResult()


# ── recherche WoS : fetch_async via http_mock ──────────────────────


class TestWosFetchAsync:
    @staticmethod
    def _adapter() -> WosDoiSearch:
        return _sans_config(
            WosDoiSearch,
            base_url="https://api.clarivate.com/api/wos",
            headers={"X-ApiKey": "k", "Accept": "application/json"},
        )

    @pytest.mark.asyncio
    async def test_fetch_async_single_page(self, http_mock):
        """Lot de DOIs qui tient sur une seule page."""
        http_mock.get("https://api.clarivate.com/api/wos").mock(
            return_value=httpx2.Response(
                200,
                json={
                    "QueryResult": {"RecordsFound": 2},
                    "Data": {
                        "Records": {"records": {"REC": [{"UID": "WOS:001"}, {"UID": "WOS:002"}]}}
                    },
                },
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a", "10.1/b"])
        # Les 2 records reviennent ; les mocks n'ont pas de DOI extractible,
        # donc les 2 DOI interrogés sont aussi déclarés absents (lot complet).
        assert [r["UID"] for r in result.records] == ["WOS:001", "WOS:002"]
        assert set(result.not_found) == {"10.1/a", "10.1/b"}

    @pytest.mark.asyncio
    async def test_fetch_async_400_marks_batch_not_found(self, http_mock):
        """WoS 400 = lot sans correspondance : zéro match, tout le lot est confirmé absent."""
        http_mock.get("https://api.clarivate.com/api/wos").mock(return_value=httpx2.Response(400))
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert result == DoiBatchResult(not_found=["10.1/a"])

    @pytest.mark.asyncio
    async def test_fetch_async_http_error_concludes_nothing(self, http_mock):
        """Erreur HTTP non-400 (401/403/5xx) = lot non fiable : aucun DOI déclaré absent, sans exception propagée."""
        http_mock.get("https://api.clarivate.com/api/wos").mock(return_value=httpx2.Response(401))
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert result == DoiBatchResult()

    @pytest.mark.asyncio
    async def test_fetch_async_network_error_concludes_nothing(self, http_mock):
        """Erreur réseau persistante = lot incomplet : aucun DOI déclaré absent."""
        http_mock.get("https://api.clarivate.com/api/wos").mock(
            side_effect=httpx2.ConnectError("refused")
        )
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(client, ["10.1/a"])
        assert result == DoiBatchResult()

    @pytest.mark.asyncio
    async def test_fetch_async_filters_preprint_dois(self, http_mock):
        """DOIs Zenodo/arXiv/SSRN sont filtrés avant appel → pas d'appel HTTP si le lot entier ne contient que des preprints."""
        route = http_mock.get("https://api.clarivate.com/api/wos")
        async with httpx2.AsyncClient() as client:
            result = await self._adapter().fetch_async(
                client, ["10.48550/arxiv.1234", "10.5281/zenodo.1"]
            )
        assert result == DoiBatchResult()
        assert route.call_count == 0
