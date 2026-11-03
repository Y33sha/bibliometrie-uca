"""File de normalisation de `staging` : mise en file à l'écriture, relevé et retrait par la normalisation, vidage du payload normalisé."""

from functools import partial

from sqlalchemy import text

from infrastructure.db.queues import Queue
from infrastructure.raw_store.local import LocalFileRawStore
from pipeline.ingestion.common.fingerprint import stable_json_bytes
from pipeline.ingestion.common.staging import StagingStore
from tests.integration.helpers.queues import clear, mark, queued
from tests.integration.helpers.staging import insert_staging

# Ligne de staging OpenAlex « W1 ».
_w1_staging = partial(insert_staging, source="openalex", source_id="W1")


def _upsert(conn, raw_data: dict, *, truncated: bool = False) -> int:
    StagingStore(conn).upsert(
        source="openalex",
        source_id="W1",
        doi=None,
        raw_data=raw_data,
        authors_truncated=truncated,
    )
    return conn.execute(
        text("SELECT id FROM staging WHERE source = 'openalex' AND source_id = 'W1'")
    ).scalar_one()


def _raw_data(conn, staging_id: int) -> dict:
    return conn.execute(
        text("SELECT raw_data FROM staging WHERE id = :i"), {"i": staging_id}
    ).scalar_one()


def _row(conn, staging_id: int):
    return StagingStore(conn).fetch_staging_by_ids([staging_id])[0]


class TestMiseEnFile:
    def test_document_nouveau_puis_modifie_en_file(self, sa_sync_conn):
        staging_id = _upsert(sa_sync_conn, {"id": "W1", "title": "A"})
        assert staging_id in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)

        clear(sa_sync_conn, Queue.STAGING_NORMALIZATION)
        _upsert(sa_sync_conn, {"id": "W1", "title": "B"})
        assert staging_id in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)

    def test_document_inchange_hors_file(self, sa_sync_conn):
        staging_id = _upsert(sa_sync_conn, {"id": "W1", "title": "A"})
        clear(sa_sync_conn, Queue.STAGING_NORMALIZATION)
        _upsert(sa_sync_conn, {"id": "W1", "title": "A"})
        assert staging_id not in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)

    def test_document_tronque_en_file_a_son_complement(self, sa_sync_conn):
        staging_id = _upsert(sa_sync_conn, {"id": "W1", "title": "A"}, truncated=True)
        assert staging_id not in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)

        StagingStore(sa_sync_conn).complete_authors("openalex", {"id": "W1", "title": "A+"})
        assert staging_id in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)

    def test_levee_de_la_troncature_met_en_file(self, sa_sync_conn):
        staging_id = _upsert(sa_sync_conn, {"id": "W1", "title": "A"}, truncated=True)
        StagingStore(sa_sync_conn).clear_truncated("openalex", "W1")
        assert staging_id in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)


class TestReleveEtRetrait:
    def test_ligne_remarquee_apres_le_releve_reste_en_file(self, sa_sync_conn):
        staging_id = _w1_staging(sa_sync_conn, raw_data={"id": "W1"})
        store = StagingStore(sa_sync_conn)
        assert store.snapshot_pending("openalex") == [staging_id]

        mark(sa_sync_conn, Queue.STAGING_NORMALIZATION, [staging_id])
        store.forget_normalized([staging_id])
        assert staging_id in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)

    def test_ligne_normalisee_retiree(self, sa_sync_conn):
        staging_id = _w1_staging(sa_sync_conn, raw_data={"id": "W1"})
        store = StagingStore(sa_sync_conn)
        store.forget_normalized(store.snapshot_pending("openalex"))
        assert staging_id not in queued(sa_sync_conn, Queue.STAGING_NORMALIZATION)

    def test_releve_borne_a_la_source(self, sa_sync_conn):
        _w1_staging(sa_sync_conn, raw_data={"id": "W1"})
        assert StagingStore(sa_sync_conn).snapshot_pending("hal") == []


class TestVidageDuPayload:
    def test_archive_puis_vide(self, sa_sync_conn, tmp_path):
        raw = {"id": "W1", "title": "Étude", "z": 1, "a": 2}
        staging_id = _w1_staging(sa_sync_conn, raw_data=raw, raw_hash="h1")
        store = LocalFileRawStore(tmp_path)

        StagingStore(sa_sync_conn, raw_store=store).clear_payload(_row(sa_sync_conn, staging_id))

        assert _raw_data(sa_sync_conn, staging_id) == {}
        assert store.get("openalex", "W1") == stable_json_bytes(raw)

    def test_ligne_reecrite_depuis_sa_lecture_garde_son_payload(self, sa_sync_conn, tmp_path):
        staging_id = _w1_staging(sa_sync_conn, raw_data={"id": "W1"}, raw_hash="h1")
        row = _row(sa_sync_conn, staging_id)
        sa_sync_conn.execute(
            text(
                'UPDATE staging SET raw_data = \'{"id": "W1", "v": 2}\', raw_hash = \'h2\''
                " WHERE id = :i"
            ),
            {"i": staging_id},
        )

        StagingStore(sa_sync_conn, raw_store=LocalFileRawStore(tmp_path)).clear_payload(row)

        assert _raw_data(sa_sync_conn, staging_id) == {"id": "W1", "v": 2}

    def test_payload_vide_non_archive(self, sa_sync_conn, tmp_path):
        staging_id = _w1_staging(sa_sync_conn)
        store = LocalFileRawStore(tmp_path)

        StagingStore(sa_sync_conn, raw_store=store).clear_payload(_row(sa_sync_conn, staging_id))

        assert store.exists("openalex", "W1") is False

    def test_echec_d_archivage_sans_consequence(self, sa_sync_conn):
        staging_id = _w1_staging(sa_sync_conn, raw_data={"id": "W1"})

        class _BoomStore:
            def put(self, *args) -> None:
                raise OSError("disk full")

        StagingStore(sa_sync_conn, raw_store=_BoomStore()).clear_payload(
            _row(sa_sync_conn, staging_id)
        )

        assert _raw_data(sa_sync_conn, staging_id) == {}
