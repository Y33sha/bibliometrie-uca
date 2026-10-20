"""Idempotence : normalisation HAL."""

from tests.integration.helpers.staging import insert_staging

HAL_STAGING_DOCS = [
    {
        "halid": "hal-99000001",
        "doi": "10.9999/hal-test-001",
        "raw_data": {
            "docType_s": "ART",
            "title_s": ["A HAL Article on Tectonics"],
            "producedDateY_i": 2024,
            "doiId_s": "10.9999/hal-test-001",
            "journalTitle_s": "Journal of Tectonics",
            "journalPublisher_s": "Test Publisher HAL",
            "authFullNameFormIDPersonIDIDHal_fs": [
                "Eve Leroy_FacetSep_0-0_FacetSep_",
                "Frank Moreau_FacetSep_0-0_FacetSep_",
            ],
            "openAccess_bool": True,
        },
    },
    {
        "halid": "hal-99000002",
        "doi": "10.9999/hal-test-002",
        "raw_data": {
            "docType_s": "COUV",
            "title_s": ["A Chapter in a Book"],
            "producedDateY_i": 2023,
            "doiId_s": "10.9999/hal-test-002",
            "bookTitle_s": "Big Book of Science",
            "publisher_s": "Academic Press",
            "authFullNameFormIDPersonIDIDHal_fs": ["Eve Leroy_FacetSep_0-0_FacetSep_"],
        },
    },
    {
        "halid": "hal-99000003",
        "doi": None,
        "raw_data": {
            "docType_s": "THESE",
            "title_s": ["Une thèse sans DOI sur la géologie"],
            "producedDateY_i": 2024,
            "authFullNameFormIDPersonIDIDHal_fs": ["Grace Petit_FacetSep_0-0_FacetSep_"],
        },
    },
]


def insert_hal_staging(conn, docs):
    for doc in docs:
        insert_staging(
            conn,
            "hal",
            source_id=doc["halid"],
            doi=doc["doi"],
            raw_data=doc["raw_data"],
            processed=False,
            upsert="processed",
        )


def run_normalize_hal(conn):
    """Exécute la normalisation HAL sur la Connection SA de test."""

    from sqlalchemy import text

    from pipeline.ingestion.common.signature_queries import AuthorshipsBatchQueries
    from pipeline.ingestion.common.source_publications import (
        SourcePublicationQueries,
    )
    from pipeline.ingestion.common.staging import StagingQueries, StagingRow
    from pipeline.ingestion.hal.normalize import process_work
    from pipeline.transformation.publishing.containers import ContainerStores
    from pipeline.transformation.publishing.publishers.store import PublisherStore

    queries = SourcePublicationQueries()
    staging_queries = StagingQueries()
    authorship_queries = AuthorshipsBatchQueries()
    container_stores = ContainerStores.of(conn)
    publisher_store = PublisherStore(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id, doi, raw_data
            FROM staging WHERE source = 'hal' AND processed = FALSE ORDER BY id
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
            conn,
            queries,
            staging_row,
            container_stores=container_stores,
            publisher_store=publisher_store,
            staging_queries=staging_queries,
            authorship_queries=authorship_queries,
        ):
            processed += 1
    return processed


def _count_hal_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for t in ("publications",):
        counts[t] = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {t}")).scalar_one()
    counts["hal_authorships"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_authorships WHERE source = 'hal'")
    ).scalar_one()
    counts["hal_documents"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_publications WHERE source = 'hal'")
    ).scalar_one()
    return counts


class TestNormalizeHalIdempotence:
    def test_double_run_same_counts(self, sa_sync_conn):
        from sqlalchemy import text

        insert_hal_staging(sa_sync_conn, HAL_STAGING_DOCS)

        processed_1 = run_normalize_hal(sa_sync_conn)
        counts_1 = _count_hal_tables(sa_sync_conn)
        assert processed_1 == 3

        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'hal'"))
        run_normalize_hal(sa_sync_conn)
        counts_2 = _count_hal_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )
