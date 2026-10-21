"""Idempotence : normalisation OpenAlex."""

from tests.integration.helpers.publications_phase import create_all_publications
from tests.integration.helpers.staging import insert_staging

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
    for doc in docs:
        insert_staging(
            conn,
            "openalex",
            source_id=doc["openalex_id"],
            doi=doc["doi"],
            raw_data=doc["raw_data"],
            processed=False,
            upsert="raw_data",
        )


def run_normalize_oa(conn):

    from sqlalchemy import text

    from pipeline.ingestion.common.source_contribution_store import SourceContributionStore
    from pipeline.ingestion.common.source_records import (
        SourceRecordStore,
    )
    from pipeline.ingestion.common.staging import StagingRow, StagingStore
    from pipeline.ingestion.openalex.normalize import process_work
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
            FROM staging WHERE source = 'openalex' AND processed = FALSE ORDER BY id
        """)
    ).all()
    processed = 0
    for row in rows:
        staging_row = StagingRow(
            id=row.id, source_id=row.source_id, doi=row.doi, raw_data=row.raw_data
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


def _count_oa_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for t in ["publications"]:
        counts[t] = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {t}")).scalar_one()
    counts["openalex_contributions"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_contributions WHERE source = 'openalex'")
    ).scalar_one()
    counts["openalex_documents"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_records WHERE source = 'openalex'")
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
