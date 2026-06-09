"""Intégration : UPSERT staging de `HalFetchMissingDoiAdapter` (`_INSERT_HAL_SQL`).

Régression : sur conflit `(source, source_id)`, le `DO UPDATE` doit renseigner
`doi` quand la ligne HAL existait sans (doc moissonné avant que HAL ne porte le
`doiId_s`). Sinon le DOI trouvé par le cross-import n'atterrit jamais et le même
lot est re-cherché à chaque run.

Teste le SQL directement (pas `adapter.insert`, qui committe et casserait
l'isolation transactionnelle du fixture).
"""

from sqlalchemy import text

from infrastructure.sources.hal.fetch_missing_doi import _INSERT_HAL_SQL


def _insert_existing(conn, source_id, doi):
    conn.execute(
        text(
            "INSERT INTO staging (source, source_id, doi, raw_data, processed, raw_hash) "
            "VALUES ('hal', :sid, :doi, '{}'::jsonb, TRUE, 'oldhash')"
        ),
        {"sid": source_id, "doi": doi},
    )


def _staging_doi(conn, source_id):
    return conn.execute(
        text("SELECT doi FROM staging WHERE source = 'hal' AND source_id = :sid"),
        {"sid": source_id},
    ).scalar_one()


def _upsert(conn, source_id, doi):
    conn.execute(
        _INSERT_HAL_SQL,
        {
            "source_id": source_id,
            "doi": doi,
            "raw_data": {"halId_s": source_id, "doiId_s": doi},
            "hal_collections": None,
            "raw_hash": "newhash",
        },
    )


def test_upsert_fills_null_doi_on_conflict(sa_sync_conn):
    _insert_existing(sa_sync_conn, "hal-99001", None)
    _upsert(sa_sync_conn, "hal-99001", "10.1/found")
    assert _staging_doi(sa_sync_conn, "hal-99001") == "10.1/found"


def test_upsert_does_not_clobber_existing_doi(sa_sync_conn):
    _insert_existing(sa_sync_conn, "hal-99002", "10.1/orig")
    _upsert(sa_sync_conn, "hal-99002", "10.1/other")
    assert _staging_doi(sa_sync_conn, "hal-99002") == "10.1/orig"
