"""Idempotence : normalisation OpenAlex."""

from tests.integration.pipeline.idempotence._helpers import create_all_publications

OA_STAGING_DOCS = [
    {
        "openalex_id": "W9990000001",
        "doi": "10.9999/oa-test-001",
        "raw_data": {
            "id": "https://openalex.org/W9990000001",
            "doi": "https://doi.org/10.9999/oa-test-001",
            "title": "An OpenAlex Article on Crystals",
            "display_name": "An OpenAlex Article on Crystals",
            "publication_year": 2024,
            "type": "article",
            "language": "en",
            "primary_location": {
                "source": {
                    "display_name": "Crystal Research Journal",
                    "type": "journal",
                    "issn": ["1111-2222"],
                    "host_organization_name": "Crystal Press",
                },
            },
            "authorships": [
                {
                    "author": {
                        "id": "https://openalex.org/A999001",
                        "display_name": "Hector Vidal",
                    },
                    "author_position": "first",
                    "institutions": [],
                    "raw_affiliation_strings": ["UCA"],
                },
            ],
            "open_access": {"oa_status": "gold", "is_oa": True},
            "cited_by_count": 5,
        },
    },
    {
        "openalex_id": "W9990000002",
        "doi": "10.9999/oa-test-002",
        "raw_data": {
            "id": "https://openalex.org/W9990000002",
            "doi": "https://doi.org/10.9999/oa-test-002",
            "title": "A Book Chapter on Minerals",
            "display_name": "A Book Chapter on Minerals",
            "publication_year": 2023,
            "type": "book-chapter",
            "primary_location": {"source": {"display_name": "Mineral Handbook", "type": "book"}},
            "authorships": [
                {
                    "author": {
                        "id": "https://openalex.org/A999001",
                        "display_name": "Hector Vidal",
                    },
                    "author_position": "first",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
            ],
            "open_access": {"oa_status": "closed", "is_oa": False},
        },
    },
    {
        "openalex_id": "W9990000003",
        "doi": None,
        "raw_data": {
            "id": "https://openalex.org/W9990000003",
            "title": "A Dissertation Without DOI",
            "display_name": "A Dissertation Without DOI",
            "publication_year": 2024,
            "type": "dissertation",
            "primary_location": {"source": None},
            "authorships": [
                {
                    "author": {"id": "https://openalex.org/A999002", "display_name": "Irene Blanc"},
                    "author_position": "first",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
            ],
            "open_access": {"oa_status": "closed", "is_oa": False},
        },
    },
]


def insert_oa_staging(conn, docs):
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import JSONB

    stmt = text("""
        INSERT INTO staging (source, source_id, doi, raw_data, processed)
        VALUES ('openalex', :openalex_id, :doi, :raw_data, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET
            processed = FALSE, raw_data = EXCLUDED.raw_data
    """).bindparams(bindparam("raw_data", type_=JSONB))
    for doc in docs:
        conn.execute(
            stmt,
            {"openalex_id": doc["openalex_id"], "doi": doc["doi"], "raw_data": doc["raw_data"]},
        )


def run_normalize_oa(conn):
    import logging

    from sqlalchemy import text

    from application.pipeline.normalize.normalize_openalex import process_work
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.db.queries.normalize_openalex import PgOpenalexNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )
    from infrastructure.sources.zenodo import HttpZenodoResolver

    queries = PgOpenalexNormalizeQueries()
    staging_queries = PgStagingQueries()
    address_linker = PgAddressLinker()
    zenodo_resolver = HttpZenodoResolver(api_base="https://zenodo.org/api/records")
    logger = logging.getLogger("test")
    journal_repo = journal_repository(conn)
    publisher_repo = publisher_repository(conn)
    pub_repo = publication_repository(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id AS openalex_id, doi, raw_data
            FROM staging WHERE source = 'openalex' AND processed = FALSE ORDER BY id
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


def _count_oa_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for t in ["publications"]:
        counts[t] = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {t}")).scalar_one()
    counts["openalex_authorships"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_authorships WHERE source = 'openalex'")
    ).scalar_one()
    counts["openalex_documents"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_publications WHERE source = 'openalex'")
    ).scalar_one()
    return counts


class TestNormalizeOpenalexIdempotence:
    def test_double_run_same_counts(self, sa_sync_conn):
        insert_oa_staging(sa_sync_conn, OA_STAGING_DOCS)

        processed_1 = run_normalize_oa(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_1 = _count_oa_tables(sa_sync_conn)
        assert processed_1 == 3

        # Réinjecter le raw_data (vidé par le normaliseur) et relancer
        insert_oa_staging(sa_sync_conn, OA_STAGING_DOCS)
        run_normalize_oa(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_2 = _count_oa_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )
