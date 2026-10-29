"""`StagingStore.upsert` efface le marqueur de disparition : un document retrouvé dans un harvest bulk est présent dans sa source."""

from sqlalchemy import text

from pipeline.ingestion.common.staging import StagingStore


def test_bulk_upsert_clears_disappeared_marker(sa_sync_conn):
    # Document présent, puis absent de sa source selon `fetch_stale` (`disappeared_at` posé).
    StagingStore(sa_sync_conn).upsert(
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
    StagingStore(sa_sync_conn).upsert(
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
