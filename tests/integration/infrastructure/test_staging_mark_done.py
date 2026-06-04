"""`mark_done` archive le `raw_data` au raw store puis le vide."""

import hashlib
import json

from sqlalchemy import text

from infrastructure.queries.pipeline.staging import PgStagingQueries
from infrastructure.raw_store.local import LocalFileRawStore
from infrastructure.sources.common import canonical_json_bytes, compute_hash


def _insert(conn, raw_json: str, *, processed: bool = False) -> int:
    return conn.execute(
        text(
            "INSERT INTO staging (source, source_id, raw_data, processed) "
            "VALUES ('openalex', 'W1', CAST(:rd AS jsonb), :p) RETURNING id"
        ),
        {"rd": raw_json, "p": processed},
    ).scalar_one()


class TestMarkDoneArchivesRaw:
    def test_archives_canonical_then_clears(self, sa_sync_conn, tmp_path):
        raw = {"id": "W1", "title": "Étude", "z": 1, "a": 2}
        sid = _insert(sa_sync_conn, json.dumps(raw))
        store = LocalFileRawStore(tmp_path)

        PgStagingQueries(raw_store=store).mark_done(sa_sync_conn, sid)

        # raw_data vidé + processed posé
        rd, processed = sa_sync_conn.execute(
            text("SELECT raw_data, processed FROM staging WHERE id = :i"), {"i": sid}
        ).one()
        assert rd == {}
        assert processed is True

        # contenu raw store = JSON canonique, et son md5 == compute_hash (== raw_hash)
        content = store.get("openalex", "W1")
        assert content == canonical_json_bytes(raw)
        assert hashlib.md5(content).hexdigest() == compute_hash(raw)

    def test_empty_raw_data_not_archived(self, sa_sync_conn, tmp_path):
        sid = _insert(sa_sync_conn, "{}", processed=True)
        store = LocalFileRawStore(tmp_path)

        PgStagingQueries(raw_store=store).mark_done(sa_sync_conn, sid)

        assert store.exists("openalex", "W1") is False

    def test_put_failure_is_best_effort(self, sa_sync_conn, tmp_path):
        sid = _insert(sa_sync_conn, json.dumps({"id": "W1"}))

        class _BoomStore:
            def put(self, *args) -> None:
                raise OSError("disk full")

        # ne lève pas, et vide quand même raw_data (la BDD reste maîtresse)
        PgStagingQueries(raw_store=_BoomStore()).mark_done(sa_sync_conn, sid)

        rd = sa_sync_conn.execute(
            text("SELECT raw_data FROM staging WHERE id = :i"), {"i": sid}
        ).scalar_one()
        assert rd == {}
