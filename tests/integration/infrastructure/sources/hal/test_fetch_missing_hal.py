"""Tests d'intégration pour `infrastructure.sources.hal.fetch_missing_hal`."""

import httpx2
import pytest
from sqlalchemy import bindparam, text

from application.ports.pipeline.fetch_missing.hal import NntInsertResult
from infrastructure.db.jsonb import Jsonb
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

_INSERT_SOURCE_PUB_SQL = text(
    """
    INSERT INTO source_publications (source, source_id, staging_id, publication_id, title, external_ids)
    VALUES (CAST(:source AS source_type), :sid, :staging_id, :pub_id, 'titre test', :external_ids)
    """
).bindparams(bindparam("external_ids", type_=Jsonb))


def _insert_publication(conn, *, in_perimeter=True, doc_type="article") -> int:
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, in_perimeter, doc_type) "
            "VALUES ('titre test', 2020, :perim, CAST(:doc_type AS doc_type)) RETURNING id"
        ),
        {"perim": in_perimeter, "doc_type": doc_type},
    ).scalar_one()


def _insert_sp(conn, source, source_id, external_ids, *, publication_id) -> None:
    """Crée un source_publication `source` rattaché à `publication_id`, avec sa ligne staging."""
    staging_id = conn.execute(
        text(
            "INSERT INTO staging (source, source_id, raw_data) "
            "VALUES (CAST(:src AS source_type), :sid, '{}'::jsonb) RETURNING id"
        ),
        {"src": source, "sid": source_id},
    ).scalar_one()
    conn.execute(
        _INSERT_SOURCE_PUB_SQL,
        {
            "source": source,
            "sid": source_id,
            "staging_id": staging_id,
            "pub_id": publication_id,
            "external_ids": external_ids,
        },
    )


def _insert_failed_lookup(conn, id_type, id_value, *, next_retry_sql="NULL") -> None:
    conn.execute(
        text(
            "INSERT INTO failed_lookups (source, id_type, id_value, not_found_at, next_retry) "
            f"VALUES ('hal', :t, :v, now(), {next_retry_sql})"
        ),
        {"t": id_type, "v": id_value},
    )


class TestFindMissingHalIds:
    """Récupère les hal-ids référencés par des source_publications OpenAlex ou ScanR in-périmètre.

    Le hal-id doit être porté par un `source_publications` OpenAlex ou ScanR rattaché à une publication `in_perimeter`, et absent du staging HAL.
    """

    @staticmethod
    def _carry(conn, source, source_id, hal_ids, *, in_perimeter=True):
        external_ids = {"hal_id": hal_ids} if hal_ids is not None else {}
        publication_id = _insert_publication(conn, in_perimeter=in_perimeter)
        _insert_sp(conn, source, source_id, external_ids, publication_id=publication_id)

    @staticmethod
    def _missing(conn) -> list[str]:
        return sorted(PgHalFetchMissingAdapter().find_missing_hal_ids(conn))

    def test_returns_hal_ids_from_openalex_and_scanr(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-aaa"])
        self._carry(sa_sync_conn, "openalex", "W1", ["hal-bbb"])
        assert self._missing(sa_sync_conn) == ["hal-aaa", "hal-bbb"]

    def test_excludes_when_publication_not_in_perimeter(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-bbb"], in_perimeter=False)
        assert self._missing(sa_sync_conn) == []

    def test_skips_hal_id_already_in_staging_hal(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-ccc"])
        sa_sync_conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data) VALUES ('hal', 'hal-ccc', '{}')"
            )
        )
        assert self._missing(sa_sync_conn) == []

    def test_skips_hal_id_already_searched_in_vain(self, sa_sync_conn):
        self._carry(sa_sync_conn, "scanr", "scanr-1", ["hal-ggg"])
        _insert_failed_lookup(sa_sync_conn, "hal_id", "hal-ggg")
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
    """Récupère les NNT des thèses soutenues in-périmètre sans document HAL."""

    @staticmethod
    def _thesis(conn, nnt) -> int:
        publication_id = _insert_publication(conn, doc_type="thesis")
        _insert_sp(conn, "theses", nnt, {"nnt": nnt}, publication_id=publication_id)
        return publication_id

    @staticmethod
    def _missing(conn) -> list[str]:
        return PgHalFetchMissingAdapter().find_missing_nnts(conn)

    def test_returns_nnt_of_thesis_without_hal_record(self, sa_sync_conn):
        self._thesis(sa_sync_conn, "2024UCA0001")
        assert self._missing(sa_sync_conn) == ["2024UCA0001"]

    def test_excludes_thesis_with_hal_record(self, sa_sync_conn):
        publication_id = self._thesis(sa_sync_conn, "2024UCA0001")
        _insert_sp(sa_sync_conn, "hal", "tel-01", {}, publication_id=publication_id)
        assert self._missing(sa_sync_conn) == []

    def test_excludes_nnt_carried_by_a_hal_record(self, sa_sync_conn):
        """Un document HAL porte le NNT sans être rattaché à la thèse : HAL le connaît déjà."""
        self._thesis(sa_sync_conn, "2024UCA0001")
        autre = _insert_publication(sa_sync_conn, doc_type="thesis")
        _insert_sp(sa_sync_conn, "hal", "tel-01", {"nnt": "2024UCA0001"}, publication_id=autre)
        assert self._missing(sa_sync_conn) == []

    def test_excludes_nnt_waiting_for_retry(self, sa_sync_conn):
        self._thesis(sa_sync_conn, "2024UCA0001")
        _insert_failed_lookup(
            sa_sync_conn, "nnt", "2024UCA0001", next_retry_sql="now() + interval '30 days'"
        )
        assert self._missing(sa_sync_conn) == []

    def test_retries_nnt_whose_delay_expired(self, sa_sync_conn):
        self._thesis(sa_sync_conn, "2024UCA0001")
        _insert_failed_lookup(
            sa_sync_conn, "nnt", "2024UCA0001", next_retry_sql="now() - interval '1 day'"
        )
        assert self._missing(sa_sync_conn) == ["2024UCA0001"]


class TestInsertResults:
    def test_un_hal_id_absent_de_hal_est_inscrit_definitivement(self, sa_sync_conn):
        found = PgHalFetchMissingAdapter().insert_halid_result(sa_sync_conn, "hal-01234567", None)
        row = sa_sync_conn.execute(
            text("SELECT id_type, id_value, next_retry FROM failed_lookups")
        ).one()
        assert found is False
        assert (row.id_type, row.id_value, row.next_retry) == ("hal_id", "hal-01234567", None)

    def test_un_nnt_absent_de_hal_attend_son_delai(self, sa_sync_conn):
        PgHalFetchMissingAdapter().insert_nnt_result(sa_sync_conn, "2024UCA0001", None)
        row = sa_sync_conn.execute(
            text("SELECT id_type, next_retry > now() AS pending FROM failed_lookups")
        ).one()
        assert (row.id_type, row.pending) == ("nnt", True)

    def test_un_document_trouve_par_nnt_entre_en_staging(self, sa_sync_conn):
        result = PgHalFetchMissingAdapter().insert_nnt_result(
            sa_sync_conn, "2024UCA0001", {"halId_s": "tel-01"}
        )
        staged = sa_sync_conn.execute(
            text("SELECT count(*) FROM staging WHERE source = 'hal' AND source_id = 'tel-01'")
        ).scalar_one()
        assert result == NntInsertResult(api_found=True, inserted=True)
        assert staged == 1

    def test_un_document_deja_en_staging_n_est_pas_nouveau(self, sa_sync_conn):
        sa_sync_conn.execute(
            text("INSERT INTO staging (source, source_id, raw_data) VALUES ('hal', 'tel-01', '{}')")
        )
        result = PgHalFetchMissingAdapter().insert_nnt_result(
            sa_sync_conn, "2024UCA0001", {"halId_s": "tel-01"}
        )
        assert result == NntInsertResult(api_found=True, inserted=False)


class TestSearchOne:
    @staticmethod
    def _adapter() -> PgHalFetchMissingAdapter:
        adapter = PgHalFetchMissingAdapter()
        adapter.configure(None)
        return adapter

    async def test_une_reponse_vide_rend_none(self, http_mock):
        http_mock.get(API_BASE_URLS["hal"]).mock(
            return_value=httpx2.Response(200, json={"response": {"docs": []}})
        )
        async with httpx2.AsyncClient() as client:
            assert await self._adapter().fetch_by_halid(client, "hal-01234567") is None

    async def test_une_erreur_http_remonte(self, http_mock):
        """Une erreur ne prouve pas l'absence : elle remonte à l'orchestrateur, qui reporte la recherche."""
        http_mock.get(API_BASE_URLS["hal"]).mock(return_value=httpx2.Response(404))
        async with httpx2.AsyncClient() as client:
            with pytest.raises(httpx2.HTTPError):
                await self._adapter().fetch_by_nnt(client, "2024UCA0001")
