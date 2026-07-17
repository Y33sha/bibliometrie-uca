"""Idempotence : normalisation Web of Science."""

WOS_STAGING_DOCS = [
    {
        "ut": "WOS:999000001",
        "doi": "10.9999/wos-test-001",
        "raw_data": {
            "UT": "WOS:999000001",
            "TI": "A WoS Article on Polymers",
            "AU": "Lambert, Jean; Roche, Marie",
            "DT": "Article",
            "PY": "2024",
            "DI": "10.9999/wos-test-001",
            "SO": "Polymer Science Letters",
            "PU": "Polymer Press",
            "SN": "3333-4444",
            "C1": "[Lambert, J] Univ Clermont Auvergne, ICCF, Clermont Ferrand, France; [Roche, M] CNRS, France",
            "OA": "gold",
        },
    },
    {
        "ut": "WOS:999000002",
        "doi": "10.9999/wos-test-002",
        "raw_data": {
            "UT": "WOS:999000002",
            "TI": "A Review on Catalysis",
            "AU": "Lambert, Jean",
            "DT": "Review",
            "PY": "2023",
            "DI": "10.9999/wos-test-002",
            "SO": "Catalysis Reviews",
            "PU": "Taylor Francis",
        },
    },
    {
        "ut": "WOS:999000003",
        "doi": None,
        "raw_data": {
            "UT": "WOS:999000003",
            "TI": "A Technical Report Without DOI",
            "AU": "Dubois, Claire",
            "DT": "Meeting Abstract",
            "PY": "2024",
            "SO": "Conference Proceedings X",
        },
    },
]


def insert_wos_staging(conn, docs):
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import JSONB

    stmt = text("""
        INSERT INTO staging (source, source_id, doi, raw_data, processed)
        VALUES ('wos', :ut, :doi, :raw_data, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET processed = FALSE
    """).bindparams(bindparam("raw_data", type_=JSONB))
    for doc in docs:
        conn.execute(stmt, {"ut": doc["ut"], "doi": doc["doi"], "raw_data": doc["raw_data"]})


def run_normalize_wos(conn):
    import logging

    from application.pipeline.normalize.normalize_wos import process_record
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.source_publications import (
        PgSourcePublicationQueries,
    )
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    queries = PgSourcePublicationQueries()
    staging_queries = PgStagingQueries()
    authorship_queries = PgAuthorshipsBatchQueries()
    logger = logging.getLogger("test")
    journal_repo = journal_repository(conn)
    publisher_repo = publisher_repository(conn)
    pub_repo = publication_repository(conn)

    rows = staging_queries.fetch_pending_staging(conn, "wos", limit=10_000)
    processed = 0
    for row in rows:
        if process_record(
            conn,
            queries,
            logger,
            row,
            journal_repo=journal_repo,
            publisher_repo=publisher_repo,
            pub_repo=pub_repo,
            staging_queries=staging_queries,
            authorship_queries=authorship_queries,
        ):
            processed += 1
    return processed


def _count_wos_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for t in ["publications"]:
        counts[t] = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {t}")).scalar_one()
    counts["wos_authorships"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_authorships WHERE source = 'wos'")
    ).scalar_one()
    counts["wos_documents"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_publications WHERE source = 'wos'")
    ).scalar_one()
    return counts


class TestNormalizeWosIdempotence:
    def test_double_run_same_counts(self, sa_sync_conn):
        from sqlalchemy import text

        insert_wos_staging(sa_sync_conn, WOS_STAGING_DOCS)

        processed_1 = run_normalize_wos(sa_sync_conn)
        counts_1 = _count_wos_tables(sa_sync_conn)
        assert processed_1 == 3

        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'wos'"))
        run_normalize_wos(sa_sync_conn)
        counts_2 = _count_wos_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )
