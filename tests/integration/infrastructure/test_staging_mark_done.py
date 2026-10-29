"""`mark_done` archive le `raw_data` au raw store puis le vide."""

from functools import partial

from sqlalchemy import text

from infrastructure.raw_store.local import LocalFileRawStore
from pipeline.ingestion.common.fingerprint import stable_json_bytes
from pipeline.ingestion.common.staging import StagingStore
from tests.integration.helpers.staging import insert_staging

# Ligne de staging OpenAlex « W1 ».
_w1_staging = partial(insert_staging, source="openalex", source_id="W1")


class TestMarkDoneArchivesRaw:
    def test_archives_canonical_then_clears(self, sa_sync_conn, tmp_path):
        raw = {"id": "W1", "title": "Étude", "z": 1, "a": 2}
        sid = _w1_staging(sa_sync_conn, raw_data=raw)
        store = LocalFileRawStore(tmp_path)

        StagingStore(sa_sync_conn, raw_store=store).mark_done(sid)

        # `raw_data` vidé, `processed` posé.
        rd, processed = sa_sync_conn.execute(
            text("SELECT raw_data, processed FROM staging WHERE id = :i"), {"i": sid}
        ).one()
        assert rd == {}
        assert processed is True

        # Le raw store contient la sérialisation stable du payload.
        assert store.get("openalex", "W1") == stable_json_bytes(raw)

    def test_empty_raw_data_not_archived(self, sa_sync_conn, tmp_path):
        sid = _w1_staging(sa_sync_conn, processed=True)
        store = LocalFileRawStore(tmp_path)

        StagingStore(sa_sync_conn, raw_store=store).mark_done(sid)

        assert store.exists("openalex", "W1") is False

    def test_put_failure_is_best_effort(self, sa_sync_conn, tmp_path):
        sid = _w1_staging(sa_sync_conn, raw_data={"id": "W1"})

        class _BoomStore:
            def put(self, *args) -> None:
                raise OSError("disk full")

        # L'échec d'archivage ne lève pas : `raw_data` est vidé quand même.
        StagingStore(sa_sync_conn, raw_store=_BoomStore()).mark_done(sid)

        rd = sa_sync_conn.execute(
            text("SELECT raw_data FROM staging WHERE id = :i"), {"i": sid}
        ).scalar_one()
        assert rd == {}
