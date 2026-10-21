"""Fragments SQL de lecture de `corrections`, confrontés à `raw_value` sur vraie base."""

from sqlalchemy import text

from domain.source_records.corrections import raw_value, stash_entry
from infrastructure.sql_fragments import corrected, corrected_by, raw_column, stashed_raw
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record

_RAW_METADATA = {
    "doc_type": stash_entry("journal-article", "MAP_DOC_TYPE"),
    "language": stash_entry(None, "LANGUAGE_MAP"),
}


def _read(conn, expression, source_record):
    return conn.execute(
        text(f"SELECT {expression} FROM source_records sr WHERE sr.id = :id"), {"id": source_record}
    ).scalar_one()


def test_les_fragments_lisent_corrections_comme_raw_value(sa_sync_conn):
    source_record = insert_source_record(
        sa_sync_conn,
        insert_publication(sa_sync_conn),
        source="crossref",
        source_id="c-raw",
        doc_type="article",
        doi="10.1/raw",
        language="fr",
        corrections=_RAW_METADATA,
    )

    for field, column in (("doc_type", "article"), ("doi", "10.1/raw"), ("language", "fr")):
        assert _read(sa_sync_conn, raw_column(field), source_record) == raw_value(
            _RAW_METADATA, field, column
        )
    assert _read(sa_sync_conn, corrected("doc_type"), source_record) is True
    assert _read(sa_sync_conn, corrected("doi"), source_record) is False
    assert _read(sa_sync_conn, corrected_by("doc_type"), source_record) == "MAP_DOC_TYPE"
    assert _read(sa_sync_conn, corrected_by("doi"), source_record) is None
    assert _read(sa_sync_conn, stashed_raw("doc_type"), source_record) == "journal-article"
    assert _read(sa_sync_conn, stashed_raw("doi"), source_record) is None
