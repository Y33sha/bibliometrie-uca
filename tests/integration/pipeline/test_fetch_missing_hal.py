"""Recherches dans HAL de la phase `fetch_missing` : sélection des identifiants, requête Solr (`pipeline.ingestion.hal.fetch_missing`)."""

import httpx2

from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.hal.fetch_missing import get_missing_hal_ids, get_missing_nnts, search_one
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers
from tests.integration.helpers.staging import insert_failed_lookup, insert_staging


def _insert_source_record(conn, source, source_id, identifiers, *, publication_id) -> None:
    """Crée un enregistrement source `source` rattaché à `publication_id`, avec sa ligne de staging."""
    staging_id = insert_staging(conn, source, source_id=source_id)
    insert_source_record(
        conn,
        publication_id,
        source=source,
        source_id=source_id,
        title="titre test",
        staging_id=staging_id,
        identifiers=secondary_identifiers(identifiers),
    )


class TestFindMissingHalIds:
    """Hal-id à chercher : cités par un enregistrement source OpenAlex ou ScanR d'une publication du périmètre, et absents du staging HAL."""

    @staticmethod
    def _carry(conn, source, source_id, hal_ids, *, in_perimeter=True):
        identifiers = {"hal_id": hal_ids} if hal_ids is not None else {}
        publication_id = insert_publication(conn, in_perimeter=in_perimeter)
        _insert_source_record(conn, source, source_id, identifiers, publication_id=publication_id)

    @staticmethod
    def _missing(conn) -> list[str]:
        return sorted(get_missing_hal_ids(conn, retry_after_days=30))

    def test_returns_hal_ids_from_openalex_and_scanr(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-aaa"])
        self._carry(sa_sync_conn, "openalex", "W1", ["hal-bbb"])
        assert self._missing(sa_sync_conn) == ["hal-aaa", "hal-bbb"]

    def test_excludes_when_publication_not_in_perimeter(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-bbb"], in_perimeter=False)
        assert self._missing(sa_sync_conn) == []

    def test_skips_hal_id_already_in_staging_hal(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-ccc"])
        insert_staging(sa_sync_conn, source_id="hal-ccc")
        assert self._missing(sa_sync_conn) == []

    def test_skips_hal_id_already_searched_in_vain(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-ggg"])
        insert_failed_lookup(sa_sync_conn, id_type="hal_id", id_value="hal-ggg")
        assert self._missing(sa_sync_conn) == []

    def test_skips_hal_id_searched_in_vain_beyond_the_delay(self, sa_sync_conn):
        """Un hal-id absent de HAL reste écarté après le délai : HAL attribue les hal-id."""
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-hhh"])
        insert_failed_lookup(
            sa_sync_conn, id_type="hal_id", id_value="hal-hhh", not_found_days_ago=365
        )
        assert self._missing(sa_sync_conn) == []

    def test_handles_missing_hal_id_key(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", None)
        assert self._missing(sa_sync_conn) == []

    def test_hal_id_seen_by_several_records_is_returned_once(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-ddd"])
        self._carry(sa_sync_conn, "scanr", "scanr-2", ["hal-ddd"])
        self._carry(sa_sync_conn, "openalex", "W1", ["hal-ddd"])
        assert self._missing(sa_sync_conn) == ["hal-ddd"]

    def test_ignores_other_sources(self, sa_sync_conn):
        self._carry(sa_sync_conn, "wos", "WOS:1", ["hal-fff"])
        assert self._missing(sa_sync_conn) == []


class TestFindMissingNnts:
    """NNT à chercher : ceux des thèses soutenues du périmètre sans enregistrement source HAL."""

    @staticmethod
    def _thesis(conn, nnt) -> int:
        publication_id = insert_publication(conn, doc_type="thesis", in_perimeter=True)
        _insert_source_record(conn, "theses", nnt, {"nnt": nnt}, publication_id=publication_id)
        return publication_id

    @staticmethod
    def _missing(conn) -> list[str]:
        return get_missing_nnts(conn, retry_after_days=30)

    def test_returns_nnt_of_thesis_without_hal_record(self, sa_sync_conn):
        self._thesis(sa_sync_conn, "2024UCA0001")
        assert self._missing(sa_sync_conn) == ["2024UCA0001"]

    def test_excludes_thesis_with_hal_record(self, sa_sync_conn):
        publication_id = self._thesis(sa_sync_conn, "2024UCA0001")
        _insert_source_record(sa_sync_conn, "hal", "tel-01", {}, publication_id=publication_id)
        assert self._missing(sa_sync_conn) == []

    def test_excludes_nnt_carried_by_a_hal_record(self, sa_sync_conn):
        """Un enregistrement source HAL contient le NNT sans être rattaché à la thèse : HAL connaît déjà la thèse."""
        self._thesis(sa_sync_conn, "2024UCA0001")
        autre = insert_publication(sa_sync_conn, doc_type="thesis", in_perimeter=True)
        _insert_source_record(
            sa_sync_conn, "hal", "tel-01", {"nnt": "2024UCA0001"}, publication_id=autre
        )
        assert self._missing(sa_sync_conn) == []

    def test_excludes_nnt_waiting_for_retry(self, sa_sync_conn):
        self._thesis(sa_sync_conn, "2024UCA0001")
        insert_failed_lookup(
            sa_sync_conn, id_type="nnt", id_value="2024UCA0001", not_found_days_ago=10
        )
        assert self._missing(sa_sync_conn) == []

    def test_retries_nnt_whose_delay_expired(self, sa_sync_conn):
        self._thesis(sa_sync_conn, "2024UCA0001")
        insert_failed_lookup(
            sa_sync_conn, id_type="nnt", id_value="2024UCA0001", not_found_days_ago=60
        )
        assert self._missing(sa_sync_conn) == ["2024UCA0001"]


class TestSearchOne:
    async def test_une_reponse_vide_est_une_absence(self, http_mock):
        http_mock.get(API_BASE_URLS["hal"]).mock(
            return_value=httpx2.Response(200, json={"response": {"docs": []}})
        )
        async with httpx2.AsyncClient() as client:
            assert await search_one(client, "halId_s:hal-01234567", label="x") is NOT_FOUND

    async def test_une_erreur_http_rend_hal_indisponible(self, http_mock):
        """Un 404 de l'endpoint de recherche ne prouve pas l'absence : la recherche est reportée."""
        http_mock.get(API_BASE_URLS["hal"]).mock(return_value=httpx2.Response(404))
        async with httpx2.AsyncClient() as client:
            assert await search_one(client, "nntId_s:2024UCA0001", label="x") is UNAVAILABLE
