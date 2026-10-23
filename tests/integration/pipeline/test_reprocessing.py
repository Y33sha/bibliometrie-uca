"""
Tests de re-traitement : quand le raw_data du staging change,
les métadonnées de la publication doivent être mises à jour.

Vérifie la correction du bug où le court-circuit d'idempotence
(source_document existant → skip find_or_create) empêchait
la mise à jour des métadonnées lors d'un re-traitement.
"""

import copy
import logging

from sqlalchemy import text

from tests.integration.helpers.publications_phase import (
    apply_metadata_corrections,
    create_all_publications,
)
from tests.integration.helpers.staging import insert_staging

# ── Données HAL minimales ───────────────────────────────────────

HAL_DOC_CLOSED = {
    "halId_s": "tel-99990001",
    "doiId_s": None,
    "title_s": "Approche hybride pour la modélisation sémantique",
    "producedDateY_i": 2024,
    "docType_s": "THESE",
    "openAccess_bool": False,
    "language_s": ["fr"],
    "authFullNameFormIDPersonIDIDHal_fs": ["Alice Dupont_FacetSep_0-0_FacetSep_"],
}


def _insert_hal_staging(conn, doc):
    """Insère un document HAL dans staging."""
    insert_staging(
        conn,
        source_id=doc["halId_s"],
        doi=doc.get("doiId_s"),
        raw_data=doc,
        processed=False,
        upsert="raw_data",
    )


def _run_normalize_hal(conn):
    """Exécute la normalisation HAL sur les staging non traités."""

    from pipeline.ingestion.common.source_contribution_store import SourceContributionStore
    from pipeline.ingestion.common.source_records import (
        SourceRecordStore,
    )
    from pipeline.ingestion.common.staging import StagingRow, StagingStore
    from pipeline.ingestion.hal.normalize import process_work
    from pipeline.transformation.publishing.containers import ContainerStores
    from pipeline.transformation.publishing.publishers.store import PublisherStore

    record_store = SourceRecordStore(conn)
    staging_store = StagingStore(conn)
    contribution_store = SourceContributionStore(conn)
    container_stores = ContainerStores.of(conn)
    publisher_store = PublisherStore(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id, doi, raw_data
            FROM staging
            WHERE source = 'hal' AND processed = FALSE
            ORDER BY id
        """)
    ).all()
    processed = 0
    for row in rows:
        staging_row = StagingRow(
            id=row.id,
            source_id=row.source_id,
            doi=row.doi,
            raw_data=row.raw_data,
        )
        if process_work(
            record_store,
            staging_row,
            container_stores=container_stores,
            publisher_store=publisher_store,
            staging_store=staging_store,
            contribution_store=contribution_store,
        ):
            processed += 1
    return processed


def _get_publication_oa_status(conn, hal_id):
    """Retourne le oa_status de la publication liée à un source_document HAL."""
    return conn.execute(
        text("""
            SELECT p.oa_status::text AS oa_status
            FROM publications p
            JOIN source_records sr ON sr.publication_id = p.id
            WHERE sr.source = 'hal' AND sr.source_id = :hal_id
        """),
        {"hal_id": hal_id},
    ).scalar_one_or_none()


def _fetch_stale_publications(conn):
    """Rejoue la phase publications après un re-normalize, pour propager les métadonnées modifiées.

    Le re-normalize a marqué pour la réconciliation les enregistrements sources touchés ; la réconciliation les reprend donc et `refresh_from_sources` recompute les métadonnées de leurs publications. La réconciliation reprend tout enregistrement source modifié.

    Rejoue d'abord `metadata_correction` : le re-normalize a réécrit les colonnes enregistrement source avec le brut source (`THESE`, `ART`…), or `refresh_from_sources` lit la valeur corrigée en place sans re-mapper. C'est l'ordre du pipeline (phase `metadata_correction` avant la phase `publications`).
    """
    from pipeline.transformation.publications.reconciliation import reconcile

    apply_metadata_corrections(conn)

    reconcile(conn, logging.getLogger("test_reprocessing"))


# ── Tests ───────────────────────────────────────────────────────


class TestHalReprocessingUpdatesOaStatus:
    """Quand openAccess_bool passe de false à true dans le staging,
    le re-traitement doit mettre à jour oa_status de closed à green."""

    def test_closed_then_green(self, sa_sync_conn):
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # 1. Premier traitement : openAccess_bool = false → closed
        _insert_hal_staging(sa_sync_conn, HAL_DOC_CLOSED)
        _run_normalize_hal(sa_sync_conn)
        create_all_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "closed"

        # 2. Re-traitement : un fileMain_s apparaît (dépôt effectif en HAL)
        #    → green. `openAccess_bool=True` seul ne suffit plus depuis la
        #    refonte de derive_hal_oa_status (003a4bc, 16a5b14).
        updated_doc = copy.deepcopy(HAL_DOC_CLOSED)
        updated_doc["openAccess_bool"] = True
        updated_doc["fileMain_s"] = "https://hal.science/tel-99990001/document"
        _insert_hal_staging(sa_sync_conn, updated_doc)  # remet processed = FALSE
        _run_normalize_hal(sa_sync_conn)
        _fetch_stale_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "green"

    def test_closed_replaces_green_on_reprocessing(self, sa_sync_conn):
        """Un re-traitement où le dépôt HAL disparaît met à jour le statut.

        Avec refresh_from_sources, le statut est recalculé depuis les
        source_records : si HAL n'a plus de fileMain_s et que
        openAccess_bool passe à false, c'est closed.
        """
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # 1. Premier traitement avec green : fileMain_s présent → green
        open_doc = copy.deepcopy(HAL_DOC_CLOSED)
        open_doc["openAccess_bool"] = True
        open_doc["fileMain_s"] = "https://hal.science/tel-99990001/document"
        _insert_hal_staging(sa_sync_conn, open_doc)
        _run_normalize_hal(sa_sync_conn)
        create_all_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "green"

        # 2. Re-traitement : fileMain_s retiré, openAccess_bool = false
        #    → refresh_from_sources recalcule en closed.
        _insert_hal_staging(sa_sync_conn, HAL_DOC_CLOSED)
        _run_normalize_hal(sa_sync_conn)
        _fetch_stale_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "closed"

    def test_deposit_floor_reopens_frozen_closed(self, sa_sync_conn):
        """Unpaywall donne closed pour le DOI, sans voir le dépôt, mais HAL détient le fichier (green) : la phase publications garde green."""
        hal_id = HAL_DOC_CLOSED["halId_s"]
        open_doc = copy.deepcopy(HAL_DOC_CLOSED)
        open_doc["doiId_s"] = "10.9999/tel-99990001"
        open_doc["openAccess_bool"] = True
        open_doc["fileMain_s"] = "https://hal.science/tel-99990001/document"
        _insert_hal_staging(sa_sync_conn, open_doc)
        _run_normalize_hal(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "green"

        # Unpaywall ne voit pas le dépôt HAL sous le DOI.
        sa_sync_conn.execute(
            text("""
                INSERT INTO unpaywall (doi, oa_status, checked_at)
                SELECT lower(doi), 'closed', now() FROM publications
                WHERE id = (
                    SELECT publication_id FROM source_records
                    WHERE source = 'hal' AND source_id = :hid
                )
            """),
            {"hid": hal_id},
        )

        # Re-dirty l'enregistrement source et rejouer la seule phase publications : le dépôt tient.
        _insert_hal_staging(sa_sync_conn, open_doc)
        _run_normalize_hal(sa_sync_conn)
        _fetch_stale_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "green"
