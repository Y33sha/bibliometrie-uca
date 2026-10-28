"""Recherche dans ScanR par hal-id de la phase `fetch_missing` : sélection des hal-id, requête ElasticSearch (`pipeline.ingestion.scanr.fetch_missing`)."""

import httpx2
import pytest

from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.scanr.fetch_missing import get_missing_hal_ids, search_by_external_ids
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers
from tests.integration.helpers.staging import insert_failed_lookup, insert_staging


def _record(conn, source, source_id, identifiers=None, *, in_perimeter=True) -> None:
    """Crée un enregistrement source `source` rattaché à une publication, avec sa ligne staging."""
    publication_id = insert_publication(conn, in_perimeter=in_perimeter)
    staging_id = insert_staging(conn, source, source_id=source_id)
    insert_source_record(
        conn,
        publication_id,
        source=source,
        source_id=source_id,
        title="titre test",
        staging_id=staging_id,
        identifiers=secondary_identifiers(identifiers or {}),
    )


def _missing(conn) -> list[str]:
    return get_missing_hal_ids(conn, retry_after_days=30)


class TestFindMissingHalIds:
    def test_returns_hal_ids_from_hal_and_openalex(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-aaa")
        _record(sa_sync_conn, "openalex", "W1", {"hal_id": ["hal-bbb"]})
        assert _missing(sa_sync_conn) == ["hal-aaa", "hal-bbb"]

    def test_excludes_when_publication_not_in_perimeter(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-aaa", in_perimeter=False)
        assert _missing(sa_sync_conn) == []

    def test_skips_hal_id_carried_by_a_scanr_record(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-aaa")
        _record(sa_sync_conn, "scanr", "doi10.1/x", {"hal_id": ["hal-aaa"]})
        assert _missing(sa_sync_conn) == []

    def test_skips_hal_id_already_in_staging_scanr(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-aaa")
        insert_staging(sa_sync_conn, "scanr", source_id="halhal-aaa")
        assert _missing(sa_sync_conn) == []

    def test_skips_hal_id_searched_in_vain_within_the_delay(self, sa_sync_conn):
        _record(sa_sync_conn, "hal", "hal-aaa")
        insert_failed_lookup(sa_sync_conn, "scanr", id_type="hal_id", id_value="hal-aaa")
        assert _missing(sa_sync_conn) == []

    def test_retries_hal_id_after_the_delay(self, sa_sync_conn):
        """ScanR n'attribue pas les hal-id : un hal-id cherché en vain l'est de nouveau après le délai."""
        _record(sa_sync_conn, "hal", "hal-aaa")
        insert_failed_lookup(
            sa_sync_conn, "scanr", id_type="hal_id", id_value="hal-aaa", not_found_days_ago=60
        )
        assert _missing(sa_sync_conn) == ["hal-aaa"]

    def test_ignores_other_sources(self, sa_sync_conn):
        _record(sa_sync_conn, "wos", "WOS:1", {"hal_id": ["hal-fff"]})
        assert _missing(sa_sync_conn) == []


def _hit(scanr_id: str, hal_id: str) -> dict:
    return {"_source": {"id": scanr_id, "externalIds": [{"type": "hal", "id": hal_id}]}}


class TestSearchByHalId:
    @pytest.mark.asyncio
    async def test_hal_id_without_document_is_absent(self, http_mock):
        http_mock.post(API_BASE_URLS["scanr"]).mock(
            return_value=httpx2.Response(
                200, json={"hits": {"hits": [_hit("halhal-aaa", "hal-aaa")]}}
            )
        )
        async with httpx2.AsyncClient() as client:
            result = await search_by_external_ids(client, ["hal-aaa", "hal-bbb"], id_type="hal")
        assert [r["id"] for r in result.records] == ["halhal-aaa"]
        assert result.absent == ["hal-bbb"]
