"""
Tests de re-traitement : quand le raw_data du staging change,
les métadonnées de la publication doivent être mises à jour.

Vérifie la correction du bug où le court-circuit d'idempotence
(source_document existant → skip find_or_create) empêchait
la mise à jour des métadonnées lors d'un re-traitement.
"""

import copy

from psycopg2.extras import Json

from application.publications import find_or_create as find_or_create_publication
from application.publications import update_sources
from domain.doc_types import map_doc_type
from domain.normalize import normalize_text
from domain.publication import normalize_nnt


def _create_all_publications(cur):
    """Crée les publications pour tous les source_publications orphelins."""
    cur.execute("""
        SELECT id, source, doi, title, pub_year, doc_type, journal_id,
               oa_status, language, container_title, external_ids
        FROM source_publications WHERE publication_id IS NULL
        ORDER BY id
    """)
    for doc in cur.fetchall():
        title = doc["title"] or ""
        pub_year = doc["pub_year"]
        if not title or not pub_year:
            continue
        raw_type = doc["doc_type"] or "other"
        doc_type = map_doc_type(raw_type, doc["source"])
        ext_ids = doc["external_ids"] or {}
        nnt = ext_ids.get("nnt")
        if nnt:
            nnt = normalize_nnt(nnt)
        pub_id, _ = find_or_create_publication(
            cur,
            title=title,
            title_normalized=normalize_text(title),
            pub_year=pub_year,
            doc_type=doc_type,
            doi=doc["doi"],
            nnt=nnt,
            oa_status=doc["oa_status"] or "unknown",
            journal_id=doc["journal_id"],
            container_title=doc["container_title"],
            language=doc["language"],
            allow_create=True,
        )
        if pub_id:
            cur.execute(
                "UPDATE source_publications SET publication_id = %s WHERE id = %s",
                (pub_id, doc["id"]),
            )
            update_sources(cur, pub_id)


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


def _insert_hal_staging(cur, doc, hal_collections=None):
    """Insère un document HAL dans staging."""
    if hal_collections is None:
        hal_collections = ["TEST_COLL"]
    cur.execute(
        """
        INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, processed)
        VALUES ('hal', %s, %s, %s, %s, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = EXCLUDED.raw_data,
            processed = FALSE
    """,
        (doc["halId_s"], doc.get("doiId_s"), Json(doc), hal_collections),
    )


def _run_normalize_hal(dict_cur):
    """Exécute la normalisation HAL sur les staging non traités.

    Le normaliseur HAL utilise un curseur tuple (accès par index),
    on en crée un temporaire sur la même connexion.
    """
    from application.pipeline.normalize.normalize_hal import process_work

    conn = dict_cur.connection
    tuple_cur = conn.cursor()  # curseur standard (tuple)
    try:
        tuple_cur.execute("""
            SELECT id, source_id, doi, raw_data, hal_collections
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
    cur.execute(
        """
        SELECT p.oa_status::text
        FROM publications p
        JOIN source_publications sd ON sd.publication_id = p.id
        WHERE sd.source = 'hal' AND sd.source_id = %s
    """,
        (hal_id,),
    )
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
        _create_all_publications(db)

        assert _get_pub_oa_status(db, hal_id) == "closed"

        # 2. Re-traitement : openAccess_bool passe à true
        updated_doc = copy.deepcopy(HAL_DOC_CLOSED)
        updated_doc["openAccess_bool"] = True
        _insert_hal_staging(db, updated_doc)  # remet processed = FALSE
        _run_normalize_hal(db)

        assert _get_pub_oa_status(db, hal_id) == "green"

    def test_closed_replaces_green_on_reprocessing(self, db):
        """Un re-traitement avec openAccess_bool=false met à jour le statut.

        Avec refresh_from_sources, le statut est recalculé depuis les
        source_publications : si HAL dit maintenant 'closed', c'est closed.
        """
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # 1. Premier traitement avec green
        open_doc = copy.deepcopy(HAL_DOC_CLOSED)
        open_doc["openAccess_bool"] = True
        _insert_hal_staging(db, open_doc)
        _run_normalize_hal(db)
        _create_all_publications(db)

        assert _get_pub_oa_status(db, hal_id) == "green"

        # 2. Re-traitement avec false → refresh_from_sources recalcule
        _insert_hal_staging(db, HAL_DOC_CLOSED)
        _run_normalize_hal(db)

        assert _get_pub_oa_status(db, hal_id) == "closed"
