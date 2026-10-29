"""Fragments SQL de lecture de `corrections`, sur vraie base."""

from sqlalchemy import text

from domain.source_records.corrections import stash_entry
from domain.source_records.metadata_correction.rules import MetadataCorrectionRule
from infrastructure.sql_fragments import corrected, corrected_by, stashed_raw
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record

_CORRECTIONS = {
    "doc_type": stash_entry("thesis", MetadataCorrectionRule.THESIS_WITH_SERIAL_TO_ARTICLE),
}


def _read(conn, expression, source_record):
    return conn.execute(
        text(f"SELECT {expression} FROM source_records sr WHERE sr.id = :id"), {"id": source_record}
    ).scalar_one()


def test_les_fragments_lisent_corrections_comme_raw_value(sa_sync_conn):
    source_record = insert_source_record(
        sa_sync_conn,
        insert_publication(sa_sync_conn),
        source="datacite",
        source_id="c-raw",
        doc_type="article",
        language="fr",
        corrections=_CORRECTIONS,
    )

    assert _read(sa_sync_conn, corrected("doc_type"), source_record) is True
    assert _read(sa_sync_conn, corrected("language"), source_record) is False
    assert (
        _read(sa_sync_conn, corrected_by("doc_type"), source_record)
        == MetadataCorrectionRule.THESIS_WITH_SERIAL_TO_ARTICLE
    )
    assert _read(sa_sync_conn, corrected_by("language"), source_record) is None
    assert _read(sa_sync_conn, stashed_raw("doc_type"), source_record) == "thesis"
    assert _read(sa_sync_conn, stashed_raw("language"), source_record) is None
