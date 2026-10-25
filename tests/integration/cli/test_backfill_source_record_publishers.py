"""Oneshot `backfill_source_record_publishers` : éditeur des enregistrements sources du stock."""

from sqlalchemy import text

from infrastructure.db.queues import Queue
from interfaces.cli.oneshot.backfill_source_record_publishers import apply, changes
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_record


def _publisher_name(conn, source_record_id: int) -> str | None:
    return conn.execute(
        text(
            "SELECT p.name FROM source_records sr LEFT JOIN publishers p ON p.id = sr.publisher_id"
            " WHERE sr.id = :id"
        ),
        {"id": source_record_id},
    ).scalar_one()


def test_rattache_l_editeur_nomme_sauf_production_hebergee(sa_sync_conn):
    article = insert_source_record(
        sa_sync_conn,
        source="hal",
        source_id="hal-1",
        doc_type="article",
        biblio={"publisher": "Armand Colin"},
        marked=False,
    )
    copy = insert_source_record(
        sa_sync_conn,
        source="datacite",
        source_id="10.5281/zenodo.1",
        doc_type="article",
        biblio={"publisher": "Zenodo"},
        marked=False,
    )
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    apply(sa_sync_conn, changes(sa_sync_conn))

    assert _publisher_name(sa_sync_conn, article) == "Armand Colin"
    assert _publisher_name(sa_sync_conn, copy) is None
    assert queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS) == {article}
    assert changes(sa_sync_conn) == []
