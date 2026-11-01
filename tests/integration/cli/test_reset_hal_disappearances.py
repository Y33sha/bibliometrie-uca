"""Oneshot `reset_hal_disappearances` : marque de disparition retirée des seuls dépôts HAL."""

from sqlalchemy import text

from interfaces.cli.oneshot.reset_hal_disappearances import reset_hal_disappearances
from tests.integration.helpers.staging import insert_staging


def _disappeared(conn) -> set[tuple[str, str]]:
    return {
        (r.source, r.source_id)
        for r in conn.execute(
            text("SELECT source::text, source_id FROM staging WHERE disappeared_at IS NOT NULL")
        )
    }


def test_retire_la_marque_des_seuls_depots_hal(sa_sync_conn):
    insert_staging(sa_sync_conn, "hal", source_id="hal-1", disappeared=True)
    insert_staging(sa_sync_conn, "scanr", source_id="halhal-1", disappeared=True)

    assert reset_hal_disappearances(sa_sync_conn, dry_run=True) == 1
    assert _disappeared(sa_sync_conn) == {("hal", "hal-1"), ("scanr", "halhal-1")}

    assert reset_hal_disappearances(sa_sync_conn) == 1
    assert _disappeared(sa_sync_conn) == {("scanr", "halhal-1")}
