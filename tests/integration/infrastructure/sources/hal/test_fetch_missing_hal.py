"""Tests d'intégration pour `infrastructure.sources.hal.fetch_missing_hal`."""

from sqlalchemy import bindparam, text

from infrastructure.db.jsonb import Jsonb
from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

_INSERT_SOURCE_PUB_SQL = text(
    """
    INSERT INTO source_publications (source, source_id, staging_id, publication_id, title, external_ids)
    VALUES (CAST(:source AS source_type), :sid, :staging_id, :pub_id, 'titre test', :external_ids)
    """
).bindparams(bindparam("external_ids", type_=Jsonb))


def _missing_hal_ids(conn) -> list[str]:
    return sorted(PgHalFetchMissingAdapter().find_missing_hal_ids(conn))


class TestFindMissingHalIds:
    """Récupère les hal-ids référencés par des source_publications OpenAlex ou ScanR in-périmètre.

    Le hal-id doit être porté par un `source_publications` OpenAlex ou ScanR rattaché à une publication `in_perimeter`, et absent du staging HAL.
    """

    def _insert_sp(self, conn, source, source_id, hal_ids, *, in_perimeter=True):
        """Crée une publication (in_perimeter réglable) et un source_publication `source` rattaché, portant `hal_ids` dans external_ids->'hal_id'."""
        staging_id = conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data) "
                "VALUES (CAST(:src AS source_type), :sid, '{}'::jsonb) RETURNING id"
            ),
            {"src": source, "sid": source_id},
        ).scalar_one()
        pub_id = conn.execute(
            text(
                "INSERT INTO publications (title, pub_year, in_perimeter) "
                "VALUES ('titre test', 2020, :perim) RETURNING id"
            ),
            {"perim": in_perimeter},
        ).scalar_one()
        external_ids = {"hal_id": hal_ids} if hal_ids is not None else {}
        conn.execute(
            _INSERT_SOURCE_PUB_SQL,
            {
                "source": source,
                "sid": source_id,
                "staging_id": staging_id,
                "pub_id": pub_id,
                "external_ids": external_ids,
            },
        )

    def _insert_hal_staging(self, conn, hal_id):
        conn.execute(
            text("INSERT INTO staging (source, source_id, raw_data) VALUES ('hal', :id, '{}')"),
            {"id": hal_id},
        )

    def test_returns_hal_ids_from_openalex_and_scanr(self, sa_sync_conn):
        self._insert_sp(sa_sync_conn, "scanr", "scanr-1", ["hal-aaa"])
        self._insert_sp(sa_sync_conn, "openalex", "W1", ["hal-bbb"])
        assert _missing_hal_ids(sa_sync_conn) == ["hal-aaa", "hal-bbb"]

    def test_excludes_when_publication_not_in_perimeter(self, sa_sync_conn):
        self._insert_sp(sa_sync_conn, "scanr", "scanr-1", ["hal-bbb"], in_perimeter=False)
        assert _missing_hal_ids(sa_sync_conn) == []

    def test_skips_hal_id_already_in_staging_hal(self, sa_sync_conn):
        self._insert_sp(sa_sync_conn, "scanr", "scanr-1", ["hal-ccc"])
        self._insert_hal_staging(sa_sync_conn, "hal-ccc")
        assert _missing_hal_ids(sa_sync_conn) == []

    def test_handles_missing_hal_id_key(self, sa_sync_conn):
        self._insert_sp(sa_sync_conn, "scanr", "scanr-1", None)
        assert _missing_hal_ids(sa_sync_conn) == []

    def test_hal_id_seen_by_several_records_is_returned_once(self, sa_sync_conn):
        self._insert_sp(sa_sync_conn, "scanr", "scanr-1", ["hal-ddd"])
        self._insert_sp(sa_sync_conn, "scanr", "scanr-2", ["hal-ddd"])
        self._insert_sp(sa_sync_conn, "openalex", "W1", ["hal-ddd"])
        assert _missing_hal_ids(sa_sync_conn) == ["hal-ddd"]

    def test_ignores_other_sources(self, sa_sync_conn):
        self._insert_sp(sa_sync_conn, "wos", "WOS:1", ["hal-fff"])
        assert _missing_hal_ids(sa_sync_conn) == []
