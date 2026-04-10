"""
Tests de re-traitement : quand le raw_data du staging change,
les métadonnées de la publication doivent être mises à jour.

Vérifie la correction du bug où le court-circuit d'idempotence
(source_document existant → skip find_or_create) empêchait
la mise à jour des métadonnées lors d'un re-traitement.
"""

import copy
import pytest
from psycopg2.extras import Json


# ── Données HAL minimales ───────────────────────────────────────

HAL_DOC_CLOSED = {
    "halId_s": "tel-99990001",
    "doiId_s": None,
    "title_s": "Approche hybride pour la modélisation sémantique",
    "producedDateY_i": 2024,
    "docType_s": "THESE",
    "openAccess_bool": False,
    "language_s": ["fr"],
    "authIdHasStructure_fs": [],
    "authFullName_s": ["Alice Dupont"],
    "authIdForm_i": [[100, 200]],
    "authIdHal_s": [None],
    "authIdHal_i": [None],
    "authOrcidIdExt_id": [None],
}


def _insert_hal_staging(cur, doc, collection="TEST_COLL"):
    """Insère un document HAL dans staging."""
    cur.execute("""
        INSERT INTO staging (source, source_id, doi, raw_data, collection, processed)
        VALUES ('hal', %s, %s, %s, %s, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = EXCLUDED.raw_data,
            processed = FALSE
    """, (doc["halId_s"], doc.get("doiId_s"), Json(doc), collection))


def _run_normalize_hal(dict_cur):
    """Exécute la normalisation HAL sur les staging non traités.

    Le normaliseur HAL utilise un curseur tuple (accès par index),
    on en crée un temporaire sur la même connexion.
    """
    from processing.normalize_hal import process_work

    conn = dict_cur.connection
    tuple_cur = conn.cursor()  # curseur standard (tuple)
    try:
        tuple_cur.execute("""
            SELECT id, source_id, doi, raw_data, collection
            FROM staging
            WHERE source = 'hal' AND processed = FALSE
            ORDER BY id
        """)
        rows = tuple_cur.fetchall()
        processed = 0
        for row in rows:
            if process_work(tuple_cur, row):
                processed += 1
        return processed
    finally:
        tuple_cur.close()


def _get_pub_oa_status(cur, hal_id):
    """Retourne le oa_status de la publication liée à un source_document HAL."""
    cur.execute("""
        SELECT p.oa_status::text
        FROM publications p
        JOIN source_documents sd ON sd.publication_id = p.id
        WHERE sd.source = 'hal' AND sd.source_id = %s
    """, (hal_id,))
    row = cur.fetchone()
    return row["oa_status"] if row else None


# ── Tests ───────────────────────────────────────────────────────


class TestHalReprocessingUpdatesOaStatus:
    """Quand openAccess_bool passe de false à true dans le staging,
    le re-traitement doit mettre à jour oa_status de closed à green."""

    def test_closed_then_green(self, db):
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # 1. Premier traitement : openAccess_bool = false → closed
        _insert_hal_staging(db, HAL_DOC_CLOSED)
        _run_normalize_hal(db)

        assert _get_pub_oa_status(db, hal_id) == "closed"

        # 2. Re-traitement : openAccess_bool passe à true
        updated_doc = copy.deepcopy(HAL_DOC_CLOSED)
        updated_doc["openAccess_bool"] = True
        _insert_hal_staging(db, updated_doc)  # remet processed = FALSE
        _run_normalize_hal(db)

        assert _get_pub_oa_status(db, hal_id) == "green"

    def test_green_not_downgraded(self, db):
        """Un re-traitement avec openAccess_bool=false ne doit pas
        rétrograder une publication déjà en green."""
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # 1. Premier traitement avec green
        open_doc = copy.deepcopy(HAL_DOC_CLOSED)
        open_doc["openAccess_bool"] = True
        _insert_hal_staging(db, open_doc)
        _run_normalize_hal(db)

        assert _get_pub_oa_status(db, hal_id) == "green"

        # 2. Re-traitement avec false (ne devrait pas rétrograder)
        _insert_hal_staging(db, HAL_DOC_CLOSED)
        _run_normalize_hal(db)

        # _enrich ne dégrade pas : green reste green
        assert _get_pub_oa_status(db, hal_id) == "green"
