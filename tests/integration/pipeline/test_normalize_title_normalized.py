"""Intégration : l'upsert normalize écrit `title_normalized` au même mouvement que `title`."""

from sqlalchemy import text

from domain.publications.metadata import normalized_title
from pipeline.ingestion.common.source_records import (
    SourceRecordQueries,
    SourceRecordUpsert,
)
from tests.integration.helpers.staging import insert_staging

_Q = SourceRecordQueries()


def test_upsert_writes_title_normalized(sa_sync_conn):
    conn = sa_sync_conn
    staging_id = insert_staging(conn, "openalex", source_id="W_title_norm")
    raw_title = "Les Cœurs <b>simples</b> &amp;amp; complexes"
    source_record_id = _Q.upsert_source_record(
        conn,
        SourceRecordUpsert(
            source="openalex",
            source_id="W_title_norm",
            staging_id=staging_id,
            title=raw_title,
            publication_year=2020,
            raw_doc_type="article",
        ),
    )
    stored = conn.execute(
        text("SELECT title, title_normalized FROM source_records WHERE id = :id"),
        {"id": source_record_id},
    ).one()
    assert stored.title == raw_title  # le titre brut est conservé tel quel
    assert stored.title_normalized == normalized_title(raw_title)
    assert stored.title_normalized  # non vide / non NULL
