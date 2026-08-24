"""`upsert_staging` efface les marqueurs d'absence : un document retrouvé dans un extract bulk n'est ni introuvable ni disparu.

Régression : un stub `not_found_at` (cross-import HAL) suivi d'un upsert bulk repassait `processed` à FALSE sans effacer `not_found_at`, violant `staging_not_found_at_implies_processed`.
"""

from sqlalchemy import text

from infrastructure.pipeline.extract.staging import upsert_not_found_stub, upsert_staging


def _row(conn, source: str, source_id: str):
    return conn.execute(
        text(
            "SELECT processed, not_found_at, disappeared_at, entry_mode "
            "FROM staging WHERE source = :s AND source_id = :sid"
        ),
        {"s": source, "sid": source_id},
    ).one()


def test_bulk_upsert_clears_not_found_stub(sa_sync_conn):
    # Stub « introuvable » posé par le cross-import HAL : not_found_at set, processed TRUE.
    upsert_not_found_stub(
        sa_sync_conn,
        source="hal",
        source_id="hal-05315879",
        doi="10.17180/ciag-2025-vol100-art01-gb",
        entry_mode="cross_import_hal",
    )

    # Le document réapparaît dans l'extraction bulk : ne doit pas violer la contrainte.
    upsert_staging(
        sa_sync_conn,
        source="hal",
        source_id="hal-05315879",
        doi="10.17180/ciag-2025-vol100-art01-gb",
        raw_data={"uri_s": "https://hal.inrae.fr/hal-05315879v1", "label_s": "Étude"},
        entry_mode="bulk",
    )

    row = _row(sa_sync_conn, "hal", "hal-05315879")
    # Contenu à traiter → processed FALSE, mais plus aucun marqueur d'absence.
    assert row.processed is False
    assert row.not_found_at is None
    assert row.disappeared_at is None
    # entry_mode garde la provenance de première création (le stub cross-import).
    assert row.entry_mode == "cross_import_hal"


def test_bulk_upsert_clears_disappeared_marker(sa_sync_conn):
    # Document présent puis confirmé absent par refresh_stale (disappeared_at posé).
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

    row = _row(sa_sync_conn, "hal", "hal-04000001")
    assert row.disappeared_at is None
    assert row.not_found_at is None
