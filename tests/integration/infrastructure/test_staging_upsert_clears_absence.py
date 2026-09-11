"""`upsert_staging` efface le marqueur de disparition : un document retrouvé dans un extract bulk est présent dans sa source."""

from sqlalchemy import text

from infrastructure.pipeline.extract.staging import upsert_staging


def test_bulk_upsert_clears_disappeared_marker(sa_sync_conn):
    # Document présent puis confirmé absent par fetch_stale (disappeared_at posé).
    upsert_staging(
        sa_sync_conn,
        source="hal",
        source_id="hal-04000001",
        doi=None,
        raw_data={"label_s": "Version initiale"},
        entry_mode="bulk",
    )
    sa_sync_conn.execute(
        text(
            "UPDATE staging SET disappeared_at = now() "
            "WHERE source = 'hal' AND source_id = 'hal-04000001'"
        )
    )

    # Réapparition en bulk avec un contenu différent : le marqueur de disparition tombe.
    upsert_staging(
        sa_sync_conn,
        source="hal",
        source_id="hal-04000001",
        doi=None,
        raw_data={"label_s": "Version révisée"},
        entry_mode="bulk",
    )

    disappeared_at = sa_sync_conn.execute(
        text(
            "SELECT disappeared_at FROM staging WHERE source = 'hal' AND source_id = 'hal-04000001'"
        )
    ).scalar_one()
    assert disappeared_at is None
