"""
Tests de re-traitement : quand le raw_data du staging change,
les métadonnées de la publication doivent être mises à jour.

Vérifie la correction du bug où le court-circuit d'idempotence
(source_document existant → skip find_or_create) empêchait
la mise à jour des métadonnées lors d'un re-traitement.
"""

import copy

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.publications import find_or_create as find_or_create_publication
from application.publications import update_sources
from domain.doc_types import map_doc_type
from domain.normalize import normalize_text
from domain.publication import normalize_nnt
from infrastructure.repositories import publication_repository


def _create_all_publications(conn):
    """Crée les publications pour tous les source_publications orphelins."""
    repo = publication_repository(conn)
    rows = conn.execute(
        text("""
            SELECT id, source, doi, title, pub_year, doc_type, journal_id,
                   oa_status, language, container_title, external_ids
            FROM source_publications WHERE publication_id IS NULL
            ORDER BY id
        """)
    ).all()
    for row in rows:
        doc = dict(row._mapping)
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
            conn,
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
            repo=repo,
        )
        if pub_id:
            conn.execute(
                text("UPDATE source_publications SET publication_id = :pid WHERE id = :sid"),
                {"pid": pub_id, "sid": doc["id"]},
            )
            update_sources(conn, pub_id, repo=repo)


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


def _insert_hal_staging(conn, doc, hal_collections=None):
    """Insère un document HAL dans staging."""
    if hal_collections is None:
        hal_collections = ["TEST_COLL"]
    stmt = text("""
        INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, processed)
        VALUES ('hal', :halid, :doi, :raw_data, :hal_collections, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = EXCLUDED.raw_data,
            processed = FALSE
    """).bindparams(bindparam("raw_data", type_=JSONB))
    conn.execute(
        stmt,
        {
            "halid": doc["halId_s"],
            "doi": doc.get("doiId_s"),
            "raw_data": doc,
            "hal_collections": hal_collections,
        },
    )


def _run_normalize_hal(conn):
    """Exécute la normalisation HAL sur les staging non traités."""
    import logging

    from application.pipeline.normalize.normalize_hal import process_work
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.db.queries.normalize_hal import PgHalNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )
    from infrastructure.zenodo import HttpZenodoResolver

    queries = PgHalNormalizeQueries()
    staging_queries = PgStagingQueries()
    address_linker = PgAddressLinker()
    zenodo_resolver = HttpZenodoResolver(api_base="https://zenodo.org/api/records")
    logger = logging.getLogger("test")
    journal_repo = journal_repository(conn)
    publisher_repo = publisher_repository(conn)
    pub_repo = publication_repository(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id, doi, raw_data, hal_collections
            FROM staging
            WHERE source = 'hal' AND processed = FALSE
            ORDER BY id
        """)
    ).all()
    processed = 0
    for row in rows:
        if process_work(
            conn,
            queries,
            logger,
            row,
            journal_repo=journal_repo,
            publisher_repo=publisher_repo,
            pub_repo=pub_repo,
            zenodo_resolver=zenodo_resolver,
            staging_queries=staging_queries,
            address_linker=address_linker,
        ):
            processed += 1
    return processed


def _get_pub_oa_status(conn, hal_id):
    """Retourne le oa_status de la publication liée à un source_document HAL."""
    return conn.execute(
        text("""
            SELECT p.oa_status::text AS oa_status
            FROM publications p
            JOIN source_publications sd ON sd.publication_id = p.id
            WHERE sd.source = 'hal' AND sd.source_id = :hal_id
        """),
        {"hal_id": hal_id},
    ).scalar_one_or_none()


# ── Tests ───────────────────────────────────────────────────────


class TestHalReprocessingUpdatesOaStatus:
    """Quand openAccess_bool passe de false à true dans le staging,
    le re-traitement doit mettre à jour oa_status de closed à green."""

    def test_closed_then_green(self, sa_sync_conn):
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # 1. Premier traitement : openAccess_bool = false → closed
        _insert_hal_staging(sa_sync_conn, HAL_DOC_CLOSED)
        _run_normalize_hal(sa_sync_conn)
        _create_all_publications(sa_sync_conn)

        assert _get_pub_oa_status(sa_sync_conn, hal_id) == "closed"

        # 2. Re-traitement : un fileMain_s apparaît (dépôt effectif en HAL)
        #    → green. `openAccess_bool=True` seul ne suffit plus depuis la
        #    refonte de derive_hal_oa_status (003a4bc, 16a5b14).
        updated_doc = copy.deepcopy(HAL_DOC_CLOSED)
        updated_doc["openAccess_bool"] = True
        updated_doc["fileMain_s"] = "https://hal.science/tel-99990001/document"
        _insert_hal_staging(sa_sync_conn, updated_doc)  # remet processed = FALSE
        _run_normalize_hal(sa_sync_conn)

        assert _get_pub_oa_status(sa_sync_conn, hal_id) == "green"

    def test_closed_replaces_green_on_reprocessing(self, sa_sync_conn):
        """Un re-traitement où le dépôt HAL disparaît met à jour le statut.

        Avec refresh_from_sources, le statut est recalculé depuis les
        source_publications : si HAL n'a plus de fileMain_s et que
        openAccess_bool passe à false, c'est closed.
        """
        hal_id = HAL_DOC_CLOSED["halId_s"]

        # 1. Premier traitement avec green : fileMain_s présent → green
        open_doc = copy.deepcopy(HAL_DOC_CLOSED)
        open_doc["openAccess_bool"] = True
        open_doc["fileMain_s"] = "https://hal.science/tel-99990001/document"
        _insert_hal_staging(sa_sync_conn, open_doc)
        _run_normalize_hal(sa_sync_conn)
        _create_all_publications(sa_sync_conn)

        assert _get_pub_oa_status(sa_sync_conn, hal_id) == "green"

        # 2. Re-traitement : fileMain_s retiré, openAccess_bool = false
        #    → refresh_from_sources recalcule en closed.
        _insert_hal_staging(sa_sync_conn, HAL_DOC_CLOSED)
        _run_normalize_hal(sa_sync_conn)

        assert _get_pub_oa_status(sa_sync_conn, hal_id) == "closed"
