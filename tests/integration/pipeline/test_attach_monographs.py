"""Rattachement en lot des enregistrements sources à leur monographie (`attach_monographs`)."""

import json
import logging

from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.transformation.publishing.monographs.attach_monographs import run_attach_monographs
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.serials import insert_monograph
from tests.integration.helpers.sources import insert_source_record

_ISBN = "9783031123450"
_EISBN = "9783031123474"


def _describe(conn, source_record_id: int, monograph: dict) -> None:
    conn.execute(
        text("UPDATE source_records SET biblio = CAST(:b AS jsonb) WHERE id = :id"),
        {"b": json.dumps({"monograph": monograph}), "id": source_record_id},
    )


def _monograph_of(conn, source_record_id: int) -> int | None:
    return conn.execute(
        text("SELECT monograph_id FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()


def _attach(conn):
    return run_attach_monographs(conn, logging.getLogger("test"))


def test_deux_enregistrements_du_meme_isbn_creent_une_monographie(sa_sync_conn):
    first = insert_source_record(sa_sync_conn, source="crossref", source_id="10.1/a")
    second = insert_source_record(sa_sync_conn, source="hal", source_id="hal-1")
    _describe(sa_sync_conn, first, {"title": "Proceedings of ICBBM", "isbns": [_ISBN]})
    _describe(sa_sync_conn, second, {"title": "Proceedings ICBBM", "eisbns": [_ISBN]})
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    metrics = _attach(sa_sync_conn)

    monograph = _monograph_of(sa_sync_conn, first)
    assert monograph is not None
    assert _monograph_of(sa_sync_conn, second) == monograph
    assert metrics.extras["monographs_created"] == 1
    assert queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS) >= {first, second}
    assert (
        sa_sync_conn.execute(
            text("SELECT isbn FROM monographs WHERE id = :id"), {"id": monograph}
        ).scalar_one()
        == _ISBN
    )


def test_les_monographies_existantes_d_un_volume_fusionnent(sa_sync_conn):
    paper = insert_monograph(sa_sync_conn, "Proceedings of ICBBM", isbn=_ISBN)
    electronic = insert_monograph(sa_sync_conn, "Proceedings of ICBBM 2025")
    sa_sync_conn.execute(
        text("UPDATE monographs SET eisbn = :e WHERE id = :id"), {"e": _EISBN, "id": electronic}
    )
    record = insert_source_record(sa_sync_conn, source="crossref", source_id="10.1/a")
    _describe(sa_sync_conn, record, {"title": "Proceedings", "isbns": [_ISBN], "eisbns": [_EISBN]})

    metrics = _attach(sa_sync_conn)

    assert _monograph_of(sa_sync_conn, record) == paper
    assert metrics.extras["monographs_merged"] == 1
    assert (
        sa_sync_conn.execute(
            text("SELECT count(*) FROM monographs WHERE id = :id"), {"id": electronic}
        ).scalar_one()
        == 0
    )


def test_un_enregistrement_sans_description_perd_sa_monographie(sa_sync_conn):
    monograph = insert_monograph(sa_sync_conn, "Livre", isbn=_ISBN)
    record = insert_source_record(
        sa_sync_conn, source="hal", source_id="hal-1", monograph_id=monograph
    )

    metrics = _attach(sa_sync_conn)

    assert _monograph_of(sa_sync_conn, record) is None
    assert metrics.extras["monographs_detached"] == 1


def test_un_second_passage_ne_change_rien(sa_sync_conn):
    record = insert_source_record(sa_sync_conn, source="crossref", source_id="10.1/a")
    _describe(sa_sync_conn, record, {"title": "Livre", "isbns": [_ISBN]})
    _attach(sa_sync_conn)
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    metrics = _attach(sa_sync_conn)

    assert metrics.updated == 0
    assert metrics.extras.get("monographs_created", 0) == 0
    assert record not in queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)
