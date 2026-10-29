"""Réhydratation de `staging` depuis le raw store, opération inverse de `StagingStore.mark_done`.

Couvre aussi le couplage au schéma (colonnes `source, source_id, doi, raw_data, raw_hash, processed`) : un renommage casserait ces requêtes.
"""

from sqlalchemy import text

from interfaces.cli.maintenance.rehydrate_staging_from_raw_store import (
    rehydrate_or_create_staging_row,
    rehydrate_staging_row,
)
from tests.integration.helpers.staging import insert_staging


def _fetch(conn, source_id):
    return conn.execute(
        text(
            "SELECT raw_data, raw_hash, processed FROM staging "
            "WHERE source = 'hal' AND source_id = :sid"
        ),
        {"sid": source_id},
    ).one_or_none()


class TestRehydrateStagingRow:
    def test_absent_row_is_orphan(self, sa_sync_conn):
        # Clé (source, source_id) orpheline : la fonction renvoie False sans créer de ligne.
        assert rehydrate_staging_row(sa_sync_conn, "hal", "hal-absent", {"x": 1}) is False
        assert _fetch(sa_sync_conn, "hal-absent") is None

    def test_updates_existing_row(self, sa_sync_conn):
        insert_staging(sa_sync_conn, source_id="hal-1", processed=True)
        assert rehydrate_staging_row(sa_sync_conn, "hal", "hal-1", {"x": 1}) is True
        row = _fetch(sa_sync_conn, "hal-1")
        assert row.raw_data == {"x": 1}
        assert row.raw_hash is not None
        assert row.processed is False


class TestRehydrateOrCreateStagingRow:
    def test_inserts_then_updates(self, sa_sync_conn):
        # Clé orpheline, par exemple après un TRUNCATE de staging : la première passe insère la ligne.
        assert rehydrate_or_create_staging_row(sa_sync_conn, "hal", "hal-2", "10.1/x", {"a": 1})
        row = _fetch(sa_sync_conn, "hal-2")
        assert row.raw_data == {"a": 1}
        assert row.processed is False

        # Deuxième passe : la ligne de même (source, source_id) est mise à jour et garde son DOI d'origine.
        assert not rehydrate_or_create_staging_row(
            sa_sync_conn, "hal", "hal-2", "10.1/other", {"a": 2}
        )
        doi = sa_sync_conn.execute(
            text("SELECT doi FROM staging WHERE source = 'hal' AND source_id = 'hal-2'")
        ).scalar_one()
        assert doi == "10.1/x"
