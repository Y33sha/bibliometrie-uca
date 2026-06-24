"""Intégration : back-fill du `doi` sur conflit, via `upsert_staging`.

Régression : sur conflit `(source, source_id)`, le `DO UPDATE` doit renseigner
`doi` quand la ligne existait sans (doc moissonné avant que la source ne porte le
DOI). Sinon le DOI trouvé par le cross-import n'atterrit jamais et le même lot est
re-cherché à chaque run. Comportement mutualisé dans `upsert_staging` (utilisé par
l'extraction bulk et tous les cross-imports).

Appelle `upsert_staging` directement (ne committe pas, l'isolation du fixture est
préservée).
"""

from sqlalchemy import text

from infrastructure.sources.common import upsert_staging


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
    upsert_staging(
        conn,
        source="hal",
        source_id=source_id,
        doi=doi,
        raw_data={"halId_s": source_id, "doiId_s": doi},
        entry_mode="cross_import_doi",
    )


def test_upsert_fills_null_doi_on_conflict(sa_sync_conn):
    _insert_existing(sa_sync_conn, "hal-99001", None)
    _upsert(sa_sync_conn, "hal-99001", "10.1/found")
    assert _staging_doi(sa_sync_conn, "hal-99001") == "10.1/found"


def test_upsert_does_not_clobber_existing_doi(sa_sync_conn):
    _insert_existing(sa_sync_conn, "hal-99002", "10.1/orig")
    _upsert(sa_sync_conn, "hal-99002", "10.1/other")
    assert _staging_doi(sa_sync_conn, "hal-99002") == "10.1/orig"
