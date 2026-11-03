"""Oneshot `fill_biblio_publisher_and_monograph` : éditeur et monographie de `biblio` relus au raw store, à défaut déduits des rattachements."""

import json

from sqlalchemy import text

from infrastructure.raw_store import LocalFileRawStore
from interfaces.cli.oneshot.fill_biblio_publisher_and_monograph import fill_source
from tests.integration.helpers.serials import insert_monograph, insert_publisher
from tests.integration.helpers.sources import insert_source_record


def _biblio(conn, source_record_id: int) -> dict | None:
    return conn.execute(
        text("SELECT biblio FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()


def _set_biblio(conn, source_record_id: int, biblio: dict) -> None:
    conn.execute(
        text("UPDATE source_records SET biblio = CAST(:b AS jsonb) WHERE id = :id"),
        {"b": json.dumps(biblio), "id": source_record_id},
    )


def test_editeur_et_monographie_relus_au_raw_store(sa_sync_conn, tmp_path):
    store = LocalFileRawStore(tmp_path)
    chapter = {
        "DOI": "10.1/ch",
        "type": "book-chapter",
        "title": ["Un chapitre"],
        "publisher": "Springer",
        "container-title": ["Bio-Based Building Materials"],
        "ISBN": ["9783031123456"],
    }
    store.put("crossref", "10.1/ch", json.dumps(chapter).encode())
    record = insert_source_record(sa_sync_conn, source="crossref", source_id="10.1/ch")
    _set_biblio(sa_sync_conn, record, {"volume": "12", "publisher": "Springer"})

    fill_source(sa_sync_conn, "crossref", store, commit=False)

    biblio = _biblio(sa_sync_conn, record)
    assert biblio["volume"] == "12"
    assert biblio["publisher"] == "Springer"
    assert biblio["monograph"]["title"] == "Bio-Based Building Materials"
    assert biblio["monograph"]["isbns"] == ["9783031123456"]


def test_document_sans_editeur_ni_numerotation_laisse_biblio_vide(sa_sync_conn, tmp_path):
    """Un `biblio` vide n'est pas un refus de la normalisation."""
    store = LocalFileRawStore(tmp_path)
    store.put("openalex", "W2", json.dumps({"id": "https://openalex.org/W2"}).encode())
    record = insert_source_record(sa_sync_conn, source="openalex", source_id="W2")

    stats = fill_source(sa_sync_conn, "openalex", store, commit=False)

    assert stats.refused == 0
    assert _biblio(sa_sync_conn, record) is None


def test_sans_payload_monographie_et_editeur_openalex_des_rattachements(sa_sync_conn, tmp_path):
    publisher = insert_publisher(sa_sync_conn, "Elsevier")
    sa_sync_conn.execute(
        text("UPDATE publishers SET openalex_id = 'P4310320990' WHERE id = :id"), {"id": publisher}
    )
    monograph = insert_monograph(
        sa_sync_conn, "Proceedings of ICBBM 2025", proceedings=True, isbn="9783031123456"
    )
    record = insert_source_record(
        sa_sync_conn,
        source="openalex",
        source_id="W1",
        monograph_id=monograph,
        publisher_id=publisher,
    )
    _set_biblio(sa_sync_conn, record, {"publisher": "Elsevier"})

    stats = fill_source(sa_sync_conn, "openalex", LocalFileRawStore(tmp_path), commit=False)

    assert stats.from_links == 1
    assert _biblio(sa_sync_conn, record) == {
        "publisher": "Elsevier",
        "publisher_openalex_id": "P4310320990",
        "monograph": {
            "title": "Proceedings of ICBBM 2025",
            "isbns": ["9783031123456"],
            "proceedings": True,
        },
    }
