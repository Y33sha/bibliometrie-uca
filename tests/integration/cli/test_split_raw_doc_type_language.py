"""Oneshot `split_raw_doc_type_language` : valeurs de la source dans `raw_doc_type` et `raw_language`, `raw_metadata` réduit aux corrections par une règle."""

from sqlalchemy import text

from interfaces.cli.oneshot.split_raw_doc_type_language import apply, fetch_rows, plan
from pipeline.ingestion.common.source_records import fetch_language_forms
from tests.integration.helpers.sources import insert_source_record


def _run(conn) -> None:
    apply(conn, plan(fetch_rows(conn), fetch_language_forms(conn)))


def _insert(conn, source_id, **columns) -> int:
    """Enregistrement source HAL à l'état d'avant la séparation : colonnes `raw_*` vides."""
    source_record = insert_source_record(conn, source="hal", source_id=source_id, **columns)
    conn.execute(
        text(
            "UPDATE source_records SET raw_doc_type = NULL, raw_language = NULL, keys_dirty = false"
            " WHERE id = :id"
        ),
        {"id": source_record},
    )
    return source_record


def _state(conn, source_record):
    return conn.execute(
        text("""
            SELECT doc_type, raw_doc_type, language, raw_language, raw_metadata, keys_dirty
            FROM source_records WHERE id = :id
        """),
        {"id": source_record},
    ).one()


def test_traduction_seule_retiree_de_raw_metadata(sa_sync_conn):
    source_record = _insert(
        sa_sync_conn,
        "hal-1",
        doc_type="article",
        language="en",
        raw_metadata={
            "doc_type": {"raw": "ART", "corrected_by": "DOC_TYPE_MAP"},
            "language": {"raw": "English", "corrected_by": "LANGUAGE_MAP"},
        },
    )

    _run(sa_sync_conn)

    row = _state(sa_sync_conn, source_record)
    assert tuple(row) == ("article", "ART", "en", "English", {}, False)


def test_regle_gardee_avec_la_valeur_traduite(sa_sync_conn):
    source_record = _insert(
        sa_sync_conn,
        "hal-2",
        doc_type="media",
        raw_metadata={"doc_type": {"raw": "ART", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}},
    )

    _run(sa_sync_conn)

    row = _state(sa_sync_conn, source_record)
    assert (row.doc_type, row.raw_doc_type) == ("media", "ART")
    assert row.raw_metadata == {
        "doc_type": {"raw": "article", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
    }


def test_enregistrement_jamais_corrige_recoit_sa_traduction(sa_sync_conn):
    source_record = _insert(sa_sync_conn, "hal-3", doc_type="COMM", language="English")

    _run(sa_sync_conn)

    row = _state(sa_sync_conn, source_record)
    assert tuple(row) == ("conference_paper", "COMM", "en", "English", {}, True)


def test_second_passage_sans_effet(sa_sync_conn):
    _insert(
        sa_sync_conn,
        "hal-4",
        doc_type="media",
        raw_metadata={"doc_type": {"raw": "ART", "corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}},
    )
    _run(sa_sync_conn)

    assert plan(fetch_rows(sa_sync_conn), fetch_language_forms(sa_sync_conn)) == []
