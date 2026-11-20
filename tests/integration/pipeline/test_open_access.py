"""Phase `open_access`, tâche `recompute_oa_status` : statut open access recalculé pour chaque publication, sans consolidation."""

import logging

from sqlalchemy import text

from pipeline.transformation.publications.open_access import recompute_oa_status
from tests.integration.helpers.publications import insert_publication


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
