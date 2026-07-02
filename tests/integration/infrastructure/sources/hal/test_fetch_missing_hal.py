"""Tests d'intégration pour `infrastructure.sources.hal.fetch_missing_hal`."""

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.sources.hal.fetch_missing_hal import find_hal_ids_from_scanr

_INSERT_SOURCE_PUB_SQL = text(
    """
    INSERT INTO source_publications (source, source_id, staging_id, publication_id, title, external_ids)
    VALUES (CAST(:source AS source_type), :sid, :staging_id, :pub_id, 'titre test', :external_ids)
    """
).bindparams(bindparam("external_ids", type_=JSONB))


class TestFindHalIdsFromScanr:
    """Récupère les hal_ids référencés par des source_publications ScanR in-périmètre.

    Le cross-import ne part que de publications confirmées UCA : le hal_id doit
    être porté par un `source_publications` ScanR rattaché à une publication
    `in_perimeter`, et absent de staging HAL.
    """

    def _insert_scanr_sp(self, conn, scanr_id, hal_ids, *, in_perimeter=True, source="scanr"):
        """Crée une publication (in_perimeter réglable) + un source_publication `source`
        rattaché, portant `hal_ids` dans external_ids->'hal_id'."""
        staging_id = conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data) "
                "VALUES (CAST(:src AS source_type), :sid, '{}'::jsonb) RETURNING id"
            ),
            {"src": source, "sid": scanr_id},
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
                "sid": scanr_id,
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

    def test_returns_hal_id_from_inperim_sp(self, sa_sync_conn):
        self._insert_scanr_sp(sa_sync_conn, "scanr-1", ["hal-aaa"])
        assert find_hal_ids_from_scanr(sa_sync_conn) == [
            {"source": "scanr", "hal_id": "hal-aaa", "scanr_id": "scanr-1"}
        ]

    def test_excludes_when_publication_not_in_perimeter(self, sa_sync_conn):
        self._insert_scanr_sp(sa_sync_conn, "scanr-1", ["hal-bbb"], in_perimeter=False)
        assert find_hal_ids_from_scanr(sa_sync_conn) == []

    def test_skips_hal_id_already_in_staging_hal(self, sa_sync_conn):
        self._insert_scanr_sp(sa_sync_conn, "scanr-1", ["hal-ccc"])
        self._insert_hal_staging(sa_sync_conn, "hal-ccc")
        assert find_hal_ids_from_scanr(sa_sync_conn) == []

    def test_handles_missing_hal_id_key(self, sa_sync_conn):
        self._insert_scanr_sp(sa_sync_conn, "scanr-1", None)
        assert find_hal_ids_from_scanr(sa_sync_conn) == []

    def test_dedup_when_multiple_scanr_sps_reference_same_hal_id(self, sa_sync_conn):
        self._insert_scanr_sp(sa_sync_conn, "scanr-1", ["hal-ddd"])
        self._insert_scanr_sp(sa_sync_conn, "scanr-2", ["hal-ddd"])
        hal_ids = [r["hal_id"] for r in find_hal_ids_from_scanr(sa_sync_conn)]
        assert hal_ids.count("hal-ddd") == 1

    def test_ignores_other_sources(self, sa_sync_conn):
        # SP in-périmètre portant un hal_id mais source != 'scanr' → ignoré.
        self._insert_scanr_sp(sa_sync_conn, "oa-1", ["hal-fff"], source="openalex")
        assert find_hal_ids_from_scanr(sa_sync_conn) == []
