"""Intégration : back-fill du `doi` sur conflit, via `StagingStore.upsert`.

Régression : sur conflit `(source, source_id)`, le `DO UPDATE` doit renseigner `doi` quand la ligne existait sans (doc moissonné avant que la source ne porte le DOI). Sinon le DOI trouvé par la phase `fetch_missing` n'atterrit jamais et le même lot est re-cherché à chaque run. Comportement mutualisé dans `StagingStore.upsert`, commun à toutes les voies d'entrée du staging.

Appelle `StagingStore.upsert` directement (ne committe pas, l'isolation du fixture est préservée).
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
