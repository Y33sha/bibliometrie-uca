"""La normalisation écrit le titre nettoyé et `title_normalized`, qui s'en dérive."""

from sqlalchemy import text

from domain.publications.metadata import normalized_title
from pipeline.ingestion.common.source_records import (
    SourceRecordStore,
    SourceRecordUpsert,
)
from tests.integration.helpers.staging import insert_staging


def test_upsert_writes_cleaned_title_and_title_normalized(sa_sync_conn):
    conn = sa_sync_conn
    staging_id = insert_staging(conn, "openalex", source_id="W_title_norm")
    raw_title = "Les  Cœurs <b>simples</b> &amp;amp; complexes"
    source_record_id = SourceRecordStore(sa_sync_conn).upsert_source_record(
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
    assert stored.title == "Les Cœurs <b>simples</b> & complexes"
    assert stored.title_normalized == normalized_title(raw_title)
    assert stored.title_normalized
