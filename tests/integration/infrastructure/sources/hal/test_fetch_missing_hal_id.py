"""Tests d'intégration pour `infrastructure.sources.hal.fetch_missing_hal_id`."""

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.sources.hal.fetch_missing_hal_id import find_hal_ids_from_scanr

_INSERT_SCANR_STAGING_SQL = text(
    "INSERT INTO staging (source, source_id, raw_data) VALUES ('scanr', :sid, :raw_data)"
).bindparams(bindparam("raw_data", type_=JSONB))

_INSERT_SOURCE_PUB_SQL = text(
    """
    INSERT INTO source_publications (source, source_id, staging_id, title, external_ids)
    VALUES ('scanr', :sid, :staging_id, 'titre test', :external_ids)
    """
).bindparams(bindparam("external_ids", type_=JSONB))


class TestFindHalIdsFromScanr:
    """Récupère les hal_ids référencés par ScanR mais absents de staging HAL.

    Régression : le bloc "staging ScanR non normalisé" matérialisait toutes les
    raw_data ScanR en mémoire Python (~1 Go × overhead psycopg → OOM kill sur
    ~80k lignes). L'extraction est désormais faite en SQL via
    `jsonb_array_elements`.
    """

    def _insert_scanr_staging(self, conn, scanr_id, external_ids):
        conn.execute(
            _INSERT_SCANR_STAGING_SQL,
            {"sid": scanr_id, "raw_data": {"externalIds": external_ids}},
        )

    def _insert_hal_staging(self, conn, hal_id):
        conn.execute(
            text("INSERT INTO staging (source, source_id, raw_data) VALUES ('hal', :id, '{}')"),
            {"id": hal_id},
        )

    def test_returns_hal_id_when_scanr_staging_has_external_id(self, sa_sync_conn):
        self._insert_scanr_staging(sa_sync_conn, "scanr-1", [{"type": "hal", "id": "hal-aaa"}])
        result = find_hal_ids_from_scanr(sa_sync_conn)
        assert result == [{"source": "scanr", "hal_id": "hal-aaa", "scanr_id": "scanr-1"}]

    def test_skips_hal_id_already_in_staging_hal(self, sa_sync_conn):
        self._insert_scanr_staging(sa_sync_conn, "scanr-1", [{"type": "hal", "id": "hal-bbb"}])
        self._insert_hal_staging(sa_sync_conn, "hal-bbb")
        assert find_hal_ids_from_scanr(sa_sync_conn) == []

    def test_skips_non_hal_external_id_types(self, sa_sync_conn):
        self._insert_scanr_staging(
            sa_sync_conn,
            "scanr-1",
            [{"type": "doi", "id": "10.1/x"}, {"type": "pubmed", "id": "999"}],
        )
        assert find_hal_ids_from_scanr(sa_sync_conn) == []

    def test_picks_hal_among_mixed_external_ids(self, sa_sync_conn):
        self._insert_scanr_staging(
            sa_sync_conn,
            "scanr-1",
            [
                {"type": "doi", "id": "10.1/x"},
                {"type": "hal", "id": "hal-ccc"},
                {"type": "pubmed", "id": "999"},
            ],
        )
        result = find_hal_ids_from_scanr(sa_sync_conn)
        assert result == [{"source": "scanr", "hal_id": "hal-ccc", "scanr_id": "scanr-1"}]

    def test_handles_missing_external_ids_field(self, sa_sync_conn):
        sa_sync_conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data) "
                "VALUES ('scanr', 'scanr-1', '{}'::jsonb)"
            )
        )
        assert find_hal_ids_from_scanr(sa_sync_conn) == []

    def test_dedup_when_multiple_scanr_docs_reference_same_hal_id(self, sa_sync_conn):
        self._insert_scanr_staging(sa_sync_conn, "scanr-1", [{"type": "hal", "id": "hal-ddd"}])
        self._insert_scanr_staging(sa_sync_conn, "scanr-2", [{"type": "hal", "id": "hal-ddd"}])
        result = find_hal_ids_from_scanr(sa_sync_conn)
        hal_ids = [r["hal_id"] for r in result]
        assert hal_ids.count("hal-ddd") == 1

    def test_picks_up_normalized_source_publications(self, sa_sync_conn):
        # source_publications.scanr → external_ids->>'hal_id' (sans staging ScanR brut)
        staging_id = sa_sync_conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data) "
                "VALUES ('scanr', 'scanr-norm', '{}'::jsonb) RETURNING id"
            )
        ).scalar_one()
        sa_sync_conn.execute(
            _INSERT_SOURCE_PUB_SQL,
            {"sid": "scanr-norm", "staging_id": staging_id, "external_ids": {"hal_id": "hal-eee"}},
        )
        result = find_hal_ids_from_scanr(sa_sync_conn)
        assert {"source": "scanr", "hal_id": "hal-eee", "scanr_id": "scanr-norm"} in result

    def test_ignores_other_sources(self, sa_sync_conn):
        # raw_data ressemble à du ScanR (externalIds[type=hal]) mais source != 'scanr'
        sa_sync_conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data) "
                "VALUES ('openalex', 'oa-1', :raw_data)"
            ).bindparams(bindparam("raw_data", type_=JSONB)),
            {"raw_data": {"externalIds": [{"type": "hal", "id": "hal-fff"}]}},
        )
        assert find_hal_ids_from_scanr(sa_sync_conn) == []
