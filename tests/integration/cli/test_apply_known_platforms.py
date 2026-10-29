"""Oneshot `apply_known_platforms` : type des plateformes, et mise en file des enregistrements sources dont le DOI a un préfixe de plateforme."""

from sqlalchemy import text

from infrastructure.db.queues import Queue
from interfaces.cli.oneshot.apply_known_platforms import (
    enqueue_platform_prefix_records,
    retype_platforms,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_record


def _platform(conn, openalex_id: str, platform_type: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO platforms (name, name_normalized, platform_type, openalex_id)"
            " VALUES (:id, :id, CAST(:t AS platform_type), :id) RETURNING id"
        ),
        {"id": openalex_id, "t": platform_type},
    ).scalar_one()


def _type(conn, platform_id: int) -> str:
    return conn.execute(
        text("SELECT platform_type::text FROM platforms WHERE id = :id"), {"id": platform_id}
    ).scalar_one()


def test_retype_les_plateformes_d_apres_la_liste(sa_sync_conn):
    arxiv = _platform(sa_sync_conn, "S4306400194", "repository")
    hal = _platform(sa_sync_conn, "S4306402512", "preprint_server")

    assert retype_platforms(sa_sync_conn) == 2
    assert (_type(sa_sync_conn, arxiv), _type(sa_sync_conn, hal)) == (
        "preprint_server",
        "repository",
    )
    assert retype_platforms(sa_sync_conn) == 0


def test_met_en_file_les_enregistrements_des_prefixes_de_plateformes(sa_sync_conn):
    cairn = insert_publication(sa_sync_conn, doi="10.3917/mult.086.0194")
    elsevier = insert_publication(sa_sync_conn, doi="10.1016/j.x.2020.01.001")
    record = insert_source_record(sa_sync_conn, cairn, source="crossref", source_id="c1")
    insert_source_record(sa_sync_conn, elsevier, source="crossref", source_id="e1")
    clear(sa_sync_conn, Queue.SOURCE_RECORD_KEYS)

    enqueue_platform_prefix_records(sa_sync_conn)

    assert queued(sa_sync_conn, Queue.SOURCE_RECORD_KEYS) == {record}
