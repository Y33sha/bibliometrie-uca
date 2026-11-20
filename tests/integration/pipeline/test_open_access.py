"""Phase `open_access`, tâche `recompute_oa_status` : statut open access recalculé pour chaque publication, sans consolidation."""

import logging

from sqlalchemy import text

from pipeline.transformation.publications.open_access import recompute_oa_status
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.serials import insert_serial


def _verdict(conn, doi: str, status: str) -> None:
    conn.execute(
        text(
            "INSERT INTO dois (doi, unpaywall_oa_status, unpaywall_checked_at)"
            " VALUES (:doi, CAST(:status AS oa_type), now())"
        ),
        {"doi": doi, "status": status},
    )


def _status(conn, publication: int) -> str:
    return conn.execute(
        text("SELECT oa_status::text FROM publications WHERE id = :id"), {"id": publication}
    ).scalar_one()


def test_un_verdict_unpaywall_change_le_statut_de_la_publication(sa_sync_conn):
    conn = sa_sync_conn
    changed = insert_publication(conn, doi="10.1/ouvert", oa_status="closed")
    _verdict(conn, "10.1/ouvert", "gold")
    kept = insert_publication(conn, doi="10.1/ferme", oa_status="closed")
    _verdict(conn, "10.1/ferme", "closed")

    metrics = recompute_oa_status(conn, logging.getLogger("test"))

    assert _status(conn, changed) == "gold"
    assert _status(conn, kept) == "closed"
    assert metrics.updated == 1
    rows = {row["key"]: row for row in metrics.details["table"]["rows"]}
    assert rows["gold"]["delta"] == 1
    assert rows["closed"]["delta"] == -1


def test_une_revue_passee_a_l_open_access_integral_donne_hybrid_avant_son_passage(sa_sync_conn):
    conn = sa_sync_conn
    serial = insert_serial(conn, "Revue passée à l'open access", oa_model="full_oa")
    conn.execute(
        text(
            "UPDATE serials SET openalex_is_oa = true, openalex_oa_flip_year = 2011 WHERE id = :id"
        ),
        {"id": serial},
    )
    before = insert_publication(conn, doi="10.1/avant", serial_id=serial, publication_year=2010)
    _verdict(conn, "10.1/avant", "gold")
    after = insert_publication(conn, doi="10.1/apres", serial_id=serial, publication_year=2011)
    _verdict(conn, "10.1/apres", "gold")

    recompute_oa_status(conn, logging.getLogger("test"))

    assert (_status(conn, before), _status(conn, after)) == ("hybrid", "gold")
