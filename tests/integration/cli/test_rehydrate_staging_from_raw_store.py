"""Smoke test de `rehydrate_staging_from_raw_store` : les requêtes couplées au schéma tournent sans buter sur une colonne périmée.

CLI de maintenance qui code en dur les colonnes de `staging` (source, source_id, doi, raw_data, raw_hash, processed) dans l'UPDATE du mode défaut et l'UPSERT du mode `--full` : un renommage les casserait en silence. Le calcul du hash et l'extraction du DOI relèvent d'autres couches et ne sont pas couverts ici.
"""

from interfaces.cli.maintenance.rehydrate_staging_from_raw_store import _UPDATE_SQL, _UPSERT_SQL

_BASE = {
    "raw_data": {"x": 1},
    "raw_hash": "deadbeef",
    "source": "hal",
    "source_id": "hal-smoke-1",
}


def test_rehydrate_schema_coupled_sql(sa_sync_conn):
    # Mode défaut : aucune ligne staging correspondante → rowcount 0 (valide les colonnes de l'UPDATE).
    assert sa_sync_conn.execute(_UPDATE_SQL, _BASE).rowcount == 0

    # Mode --full : première exécution insère (RETURNING inserted = TRUE).
    row = sa_sync_conn.execute(_UPSERT_SQL, {**_BASE, "doi": None}).one()
    assert row.inserted is True

    # Ré-exécution : conflit sur (source, source_id) → UPDATE, inserted = FALSE.
    row2 = sa_sync_conn.execute(_UPSERT_SQL, {**_BASE, "doi": None}).one()
    assert row2.inserted is False
