"""`upsert_staging` accepte une ligne entrée par l'import d'un export de l'interface d'une source."""

from sqlalchemy import text

from infrastructure.pipeline.extract.staging import upsert_staging


def test_ligne_d_export_wos(sa_sync_conn):
    inserted, _ = upsert_staging(
        sa_sync_conn,
        source="wos",
        source_id="WOS:000000000000001",
        doi="10.1/x",
        raw_data={"UT": "WOS:000000000000001", "TI": "Un titre"},
        entry_mode="manual_export",
    )
    assert inserted
    entry_mode = sa_sync_conn.execute(
        text("SELECT entry_mode FROM staging WHERE source_id = 'WOS:000000000000001'")
    ).scalar_one()
    assert entry_mode == "manual_export"
