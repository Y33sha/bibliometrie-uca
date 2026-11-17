"""Application au stock de la table de correspondance des types de document (`apply_doc_type_mapping`)."""

from functools import partial

from sqlalchemy import text

from infrastructure.db.queues import Queue
from interfaces.cli.maintenance.apply_doc_type_mapping import apply_mapping
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import queued
from tests.integration.helpers.sources import insert_source_record

_datacite = partial(insert_source_record, source="datacite", title="T", marked=False)


def _types(conn, *ids) -> list[tuple[str, str | None]]:
    rows = conn.execute(
        text(
            "SELECT id, doc_type::text, corrections->'doc_type'->>'raw' FROM source_records"
            " WHERE id = ANY(:ids)"
        ),
        {"ids": list(ids)},
    ).all()
    by_id = {r[0]: (r[1], r[2]) for r in rows}
    return [by_id[i] for i in ids]


def test_le_type_d_avant_correction_suit_la_table(sa_sync_conn):
    """Une collection DataCite stockée `other` passe `dataset`. Pour un enregistrement source corrigé, le type d'avant correction change et le type corrigé reste, à refaire par la phase `metadata_correction`."""
    conn = sa_sync_conn
    publication = insert_publication(conn, doc_type="other")
    plain = _datacite(
        conn, publication, source_id="c1", doc_type="other", raw_doc_type="Collection"
    )
    corrected = _datacite(
        conn,
        None,
        source_id="c2",
        doc_type="article",
        raw_doc_type="Collection",
        corrections={"doc_type": {"raw": "other", "corrected_by": "RULE"}},
    )
    sibling = insert_source_record(conn, publication, source="hal", source_id="h1", marked=False)
    unchanged = _datacite(conn, None, source_id="d1", doc_type="dataset", raw_doc_type="Dataset")

    apply_mapping(conn, dry_run=False)

    assert _types(conn, plain, corrected, unchanged) == [
        ("dataset", None),
        ("article", "dataset"),
        ("dataset", None),
    ]
    assert queued(conn, Queue.SOURCE_RECORD_KEYS) == {plain, corrected, sibling}


def test_simulation_sans_ecriture(sa_sync_conn):
    conn = sa_sync_conn
    record = _datacite(conn, None, source_id="c1", doc_type="other", raw_doc_type="Collection")
    apply_mapping(conn, dry_run=True)
    assert _types(conn, record) == [("other", None)]
