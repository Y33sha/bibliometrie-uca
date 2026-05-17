"""Idempotence : normalisation HAL."""

HAL_STAGING_DOCS = [
    {
        "halid": "hal-99000001",
        "doi": "10.9999/hal-test-001",
        "hal_collections": ["TEST"],
        "raw_data": {
            "docType_s": "ART",
            "title_s": ["A HAL Article on Tectonics"],
            "producedDateY_i": 2024,
            "doiId_s": "10.9999/hal-test-001",
            "journalTitle_s": "Journal of Tectonics",
            "journalPublisher_s": "Test Publisher HAL",
            "authFullName_s": ["Eve Leroy", "Frank Moreau"],
            "openAccess_bool": True,
        },
    },
    {
        "halid": "hal-99000002",
        "doi": "10.9999/hal-test-002",
        "hal_collections": ["TEST"],
        "raw_data": {
            "docType_s": "COUV",
            "title_s": ["A Chapter in a Book"],
            "producedDateY_i": 2023,
            "doiId_s": "10.9999/hal-test-002",
            "bookTitle_s": "Big Book of Science",
            "publisher_s": "Academic Press",
            "authFullName_s": ["Eve Leroy"],
        },
    },
    {
        "halid": "hal-99000003",
        "doi": None,
        "hal_collections": ["TEST"],
        "raw_data": {
            "docType_s": "THESE",
            "title_s": ["Une thèse sans DOI sur la géologie"],
            "producedDateY_i": 2024,
            "authFullName_s": ["Grace Petit"],
        },
    },
]


def insert_hal_staging(conn, docs):
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import JSONB

    stmt = text("""
        INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, processed)
        VALUES ('hal', :halid, :doi, :raw_data, :hal_collections, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET processed = FALSE
    """).bindparams(bindparam("raw_data", type_=JSONB))
    for doc in docs:
        conn.execute(
            stmt,
            {
                "halid": doc["halid"],
                "doi": doc["doi"],
                "raw_data": doc["raw_data"],
                "hal_collections": doc["hal_collections"],
            },
        )


def run_normalize_hal(conn):
    """Exécute la normalisation HAL sur la Connection SA de test."""
    import logging

    from sqlalchemy import text

    from application.pipeline.normalize.normalize_hal import process_work
    from application.ports.pipeline.staging import HalStagingRow
    from infrastructure.queries.normalize_hal import PgHalNormalizeQueries
    from infrastructure.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )
    from infrastructure.repositories.address_linker import PgAddressLinker
    from infrastructure.sources.zenodo import HttpZenodoResolver

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
            FROM staging WHERE source = 'hal' AND processed = FALSE ORDER BY id
        """)
    ).all()
    processed = 0
    for row in rows:
        staging_row = HalStagingRow(
            id=row.id,
            source_id=row.source_id,
            doi=row.doi,
            raw_data=row.raw_data,
            hal_collections=row.hal_collections,
        )
        if process_work(
            conn,
            queries,
            logger,
            staging_row,
            journal_repo=journal_repo,
            publisher_repo=publisher_repo,
            pub_repo=pub_repo,
            zenodo_resolver=zenodo_resolver,
            staging_queries=staging_queries,
            address_linker=address_linker,
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
