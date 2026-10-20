"""Fragments SQL de lecture de `raw_metadata`, confrontés à `raw_value` sur vraie base."""

from sqlalchemy import text

from domain.source_records.raw_metadata import raw_value, stash_entry
from infrastructure.sql_fragments import corrected, corrected_by, raw_column, stashed_raw
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record

_RAW_METADATA = {
    "doc_type": stash_entry("journal-article", "MAP_DOC_TYPE"),
    "language": stash_entry(None, "LANGUAGE_MAP"),
}


def _read(conn, expression, notice):
    return conn.execute(
        text(f"SELECT {expression} FROM source_records sp WHERE sp.id = :id"), {"id": notice}
    ).scalar_one()


def test_les_fragments_lisent_raw_metadata_comme_raw_value(sa_sync_conn):
    notice = insert_source_record(
        sa_sync_conn,
        insert_publication(sa_sync_conn),
        source="crossref",
        source_id="c-raw",
        doc_type="article",
        doi="10.1/raw",
        language="fr",
        raw_metadata=_RAW_METADATA,
    )

    for field, column in (("doc_type", "article"), ("doi", "10.1/raw"), ("language", "fr")):
        assert _read(sa_sync_conn, raw_column(field), notice) == raw_value(
            _RAW_METADATA, field, column
        )
    assert _read(sa_sync_conn, corrected("doc_type"), notice) is True
    assert _read(sa_sync_conn, corrected("doi"), notice) is False
    assert _read(sa_sync_conn, corrected_by("doc_type"), notice) == "MAP_DOC_TYPE"
    assert _read(sa_sync_conn, corrected_by("doi"), notice) is None
    assert _read(sa_sync_conn, stashed_raw("doc_type"), notice) == "journal-article"
    assert _read(sa_sync_conn, stashed_raw("doi"), notice) is None
