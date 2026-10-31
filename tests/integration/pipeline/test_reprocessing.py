"""Retraitement : quand le `raw_data` d'une ligne de staging change, la normalisation puis la phase `publications` mettent à jour les métadonnées de la publication."""

import copy
import logging

from sqlalchemy import text

from tests.integration.helpers.publications_phase import (
    apply_metadata_corrections,
    create_all_publications,
)
from tests.integration.helpers.staging import insert_staging, normalize_pending

# Document HAL minimal, sans dépôt de fichier.
HAL_DOC_CLOSED = {
    "halId_s": "tel-99990001",
    "uri_s": "https://theses.hal.science/tel-99990001",
    "doiId_s": None,
    "title_s": "Approche hybride pour la modélisation sémantique",
    "producedDateY_i": 2024,
    "docType_s": "THESE",
    "language_s": ["fr"],
    "authFullNameFormIDPersonIDIDHal_fs": ["Alice Dupont_FacetSep_0-0_FacetSep_"],
}


def _insert_hal_staging(conn, doc):
    """Insère un document HAL dans le staging, ou remplace son contenu et le remet à traiter."""
    insert_staging(
        conn,
        source_id=doc["halId_s"],
        doi=doc.get("doiId_s"),
        raw_data=doc,
        processed=False,
        replace=True,
    )


def _run_normalize_hal(conn):
    return normalize_pending(conn, "hal")


def _get_publication_oa_status(conn, hal_id):
    """Renvoie le statut open access de la publication de l'enregistrement source HAL `hal_id`."""
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
    """Rejoue `metadata_correction` puis la réconciliation, comme le pipeline après une renormalisation.

    La renormalisation marque les enregistrements sources modifiés pour la réconciliation, qui recalcule les métadonnées de leurs publications (`refresh_from_sources`). Elle réécrit aussi les valeurs brutes de la source (`THESE`, `ART`…) : `metadata_correction` les corrige d'abord, et `refresh_from_sources` lit les valeurs corrigées.
    """
    from pipeline.transformation.publications.reconciliation import reconcile

    apply_metadata_corrections(conn)

    reconcile(conn, logging.getLogger("test_reprocessing"))


class TestHalReprocessingUpdatesOaStatus:
    """Au retraitement, le statut open access d'une publication HAL suit le dépôt du fichier (`fileMain_s`)."""

    def test_closed_then_green(self, sa_sync_conn):
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # Premier traitement, sans dépôt : closed.
        _insert_hal_staging(sa_sync_conn, HAL_DOC_CLOSED)
        _run_normalize_hal(sa_sync_conn)
        create_all_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "closed"

        # Retraitement avec un fichier déposé dans HAL (`fileMain_s`) : green.
        updated_doc = copy.deepcopy(HAL_DOC_CLOSED)
        updated_doc["fileMain_s"] = "https://hal.science/tel-99990001/document"
        _insert_hal_staging(sa_sync_conn, updated_doc)  # remet la ligne à traiter
        _run_normalize_hal(sa_sync_conn)
        _fetch_stale_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "green"

    def test_closed_replaces_green_on_reprocessing(self, sa_sync_conn):
        """Au retraitement, une publication HAL dont le fichier déposé disparaît passe de green à closed."""
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # Premier traitement, avec dépôt : green.
        open_doc = copy.deepcopy(HAL_DOC_CLOSED)
        open_doc["fileMain_s"] = "https://hal.science/tel-99990001/document"
        _insert_hal_staging(sa_sync_conn, open_doc)
        _run_normalize_hal(sa_sync_conn)
        create_all_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "green"

        # Retraitement sans `fileMain_s` : closed.
        _insert_hal_staging(sa_sync_conn, HAL_DOC_CLOSED)
        _run_normalize_hal(sa_sync_conn)
        _fetch_stale_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "closed"

    def test_deposit_floor_reopens_frozen_closed(self, sa_sync_conn):
        """Unpaywall donne closed pour le DOI sans voir le dépôt, mais HAL a le fichier : la phase `publications` garde green."""
        hal_id = HAL_DOC_CLOSED["halId_s"]
        open_doc = copy.deepcopy(HAL_DOC_CLOSED)
        open_doc["doiId_s"] = "10.9999/tel-99990001"
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

        # La renormalisation marque l'enregistrement source ; la phase `publications` rejouée garde le statut du dépôt.
        _insert_hal_staging(sa_sync_conn, open_doc)
        _run_normalize_hal(sa_sync_conn)
        _fetch_stale_publications(sa_sync_conn)

        assert _get_publication_oa_status(sa_sync_conn, hal_id) == "green"
