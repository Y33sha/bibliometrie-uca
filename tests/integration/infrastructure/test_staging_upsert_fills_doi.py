"""`StagingStore.upsert` renseigne le `doi` vide d'une ligne existante, sans écraser un `doi` présent.

Une ligne moissonnée avant que la source ait le DOI reçoit celui trouvé par la phase `fetch_missing`. Sans cela, le même lot serait recherché à chaque run.
"""

from sqlalchemy import text

from pipeline.ingestion.common.staging import StagingStore
from tests.integration.helpers.staging import insert_staging


def _insert_existing(conn, source_id, doi):
    insert_staging(conn, source_id=source_id, doi=doi, processed=True, raw_hash="oldhash")


def _staging_doi(conn, source_id):
    return conn.execute(
        text("SELECT doi FROM staging WHERE source = 'hal' AND source_id = :sid"),
        {"sid": source_id},
    ).scalar_one()


def _upsert(conn, source_id, doi):
    StagingStore(conn).upsert(
        source="hal",
        source_id=source_id,
        doi=doi,
        raw_data={"halId_s": source_id, "doiId_s": doi},
        entry_mode="fetch_missing_doi",
    )


def test_upsert_fills_null_doi_on_conflict(sa_sync_conn):
    _insert_existing(sa_sync_conn, "hal-99001", None)
    _upsert(sa_sync_conn, "hal-99001", "10.1/found")
    assert _staging_doi(sa_sync_conn, "hal-99001") == "10.1/found"


def test_upsert_does_not_clobber_existing_doi(sa_sync_conn):
    _insert_existing(sa_sync_conn, "hal-99002", "10.1/orig")
    _upsert(sa_sync_conn, "hal-99002", "10.1/other")
    assert _staging_doi(sa_sync_conn, "hal-99002") == "10.1/orig"
