"""Idempotence : normalisation CrossRef.

CrossRef est ingérée DOI-driven (cf. `fetch_missing_doi`) puis
normalisée vers `source_publications` + `source_authorships`. Les
affiliations textuelles alimentent `addresses` /
`source_authorship_addresses`, ce qui permet à la phase `affiliations`
de poser `in_perimeter` sur les SA crossref.

Vérifie :
- Le double passage `process_work` ne crée pas de doublons (y compris
  sur les liens adresses).
- Les branches d'erreur (DOI absent, titre absent, raw_data vide)
  marquent `processed=TRUE` et n'insèrent rien.
"""

from __future__ import annotations

from tests.integration.helpers.publications_phase import create_all_publications

CROSSREF_STAGING_DOCS = [
    {
        # Cas nominal : article avec DOI, titre, année, auteurs ORCID,
        # affiliations textuelles.
        "source_id": "10.9999/cr-test-001",
        "doi": "10.9999/cr-test-001",
        "raw_data": {
            "DOI": "10.9999/cr-test-001",
            "title": ["A CrossRef Article on Topology"],
            "published": {"date-parts": [[2024]]},
            "container-title": ["Topology Quarterly"],
            "ISSN": ["1111-2222"],
            "publisher": "Topology Press",
            "language": "EN",
            "abstract": "<jats:p>Abstract <jats:bold>text</jats:bold>.</jats:p>",
            "subject": ["mathematics", "topology"],
            "is-referenced-by-count": 7,
            "volume": "5",
            "issue": "2",
            "page": "100-120",
            "author": [
                {
                    "given": "Alice",
                    "family": "Curie",
                    "ORCID": "http://orcid.org/0000-0002-1825-0097",
                    "affiliation": [{"name": "UCA"}],
                    "sequence": "first",
                },
                {
                    "given": "Bob",
                    "family": "Pasteur",
                    "affiliation": [{"name": "CNRS"}],
                    "sequence": "additional",
                },
            ],
        },
    },
    {
        # Cas minimal : DOI + titre + année, sans auteurs ni journal.
        "source_id": "10.9999/cr-test-002",
        "doi": "10.9999/cr-test-002",
        "raw_data": {
            "DOI": "10.9999/cr-test-002",
            "title": ["A Minimal CrossRef Record"],
            "published": {"date-parts": [[2023]]},
        },
    },
]


def _insert_crossref_staging(conn, docs):
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import JSONB

    stmt = text("""
        INSERT INTO staging (source, source_id, doi, raw_data, processed)
        VALUES ('crossref', :source_id, :doi, :raw_data, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET
            processed = FALSE, raw_data = EXCLUDED.raw_data
    """).bindparams(bindparam("raw_data", type_=JSONB))
    for doc in docs:
        conn.execute(stmt, doc)


def _run_normalize_crossref(conn):
    """Lance `process_work` sur tous les staging crossref non traités."""
    import logging

    from sqlalchemy import text

    from application.pipeline.normalize.normalize_crossref import process_work
    from application.ports.pipeline.normalize.staging import StagingRow
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.crossref import PgCrossrefNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    queries = PgCrossrefNormalizeQueries()
    staging_queries = PgStagingQueries()
    authorship_queries = PgAuthorshipsBatchQueries()
    logger = logging.getLogger("test")
    journal_repo = journal_repository(conn)
    publisher_repo = publisher_repository(conn)
    pub_repo = publication_repository(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id, doi, raw_data
            FROM staging WHERE source = 'crossref' AND processed = FALSE ORDER BY id
        """)
    ).all()
    processed = 0
    for row in rows:
        staging_row = StagingRow(
            id=row.id, source_id=row.source_id, doi=row.doi, raw_data=row.raw_data
        )
        if process_work(
            conn,
            queries,
            logger,
            staging_row,
            journal_repo=journal_repo,
            publisher_repo=publisher_repo,
            pub_repo=pub_repo,
            staging_queries=staging_queries,
            authorship_queries=authorship_queries,
        ):
            processed += 1
    return processed


def _count_crossref(conn) -> dict[str, int]:
    from sqlalchemy import text

    counts: dict[str, int] = {}
    counts["sp"] = conn.execute(
        text("SELECT COUNT(*) AS n FROM source_publications WHERE source = 'crossref'")
    ).scalar_one()
    counts["sa"] = conn.execute(
        text("SELECT COUNT(*) AS n FROM source_authorships WHERE source = 'crossref'")
    ).scalar_one()
    counts["saa"] = conn.execute(
        text("""
            SELECT COUNT(*) AS n
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            WHERE sa.source = 'crossref'
        """)
    ).scalar_one()
    counts["publications"] = conn.execute(
        text("SELECT COUNT(*) AS n FROM publications")
    ).scalar_one()
    counts["journals"] = conn.execute(text("SELECT COUNT(*) AS n FROM journals")).scalar_one()
    counts["publishers"] = conn.execute(text("SELECT COUNT(*) AS n FROM publishers")).scalar_one()
    return counts


class TestNormalizeCrossrefIdempotence:
    def test_double_run_same_counts(self, sa_sync_conn):
        _insert_crossref_staging(sa_sync_conn, CROSSREF_STAGING_DOCS)

        processed_1 = _run_normalize_crossref(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_1 = _count_crossref(sa_sync_conn)
        assert processed_1 == 2
        assert counts_1["sp"] == 2
        # 2 auteurs sur le 1er record, 0 sur le 2nd → 2 source_authorships.
        assert counts_1["sa"] == 2
        # 2 affiliations distinctes (UCA, CNRS) liées via address linker.
        assert counts_1["saa"] == 2

        # Réinjecter le raw_data (le normaliseur peut le purger via VACUUM
        # post-pipeline ; ici on re-stage explicitement pour relancer).
        _insert_crossref_staging(sa_sync_conn, CROSSREF_STAGING_DOCS)
        _run_normalize_crossref(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_2 = _count_crossref(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_authors_persisted_with_orcid_and_affiliations(self, sa_sync_conn):
        from sqlalchemy import text

        _insert_crossref_staging(sa_sync_conn, [CROSSREF_STAGING_DOCS[0]])
        _run_normalize_crossref(sa_sync_conn)

        rows = sa_sync_conn.execute(
            text("""
                SELECT sa.raw_author_name, aik.person_identifiers
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sa.source = 'crossref'
                ORDER BY sa.author_position
            """)
        ).all()
        assert len(rows) == 2

        # Premier auteur : ORCID.
        assert rows[0].raw_author_name == "Alice Curie"
        assert rows[0].person_identifiers is not None
        assert rows[0].person_identifiers.get("orcid") == "0000-0002-1825-0097"

        # Deuxième auteur : pas d'ORCID.
        assert rows[1].raw_author_name == "Bob Pasteur"
        assert rows[1].person_identifiers is None

        # Les affiliations sont routées vers addresses + source_authorship_addresses.
        addr_rows = sa_sync_conn.execute(
            text("""
                SELECT a.raw_text
                FROM source_authorship_addresses saa
                JOIN source_authorships sa ON sa.id = saa.source_authorship_id
                JOIN addresses a ON a.id = saa.address_id
                WHERE sa.source = 'crossref'
                ORDER BY a.raw_text
            """)
        ).all()
        assert [r.raw_text for r in addr_rows] == ["CNRS", "UCA"]


class TestNormalizeCrossrefSkipBranches:
    def test_skips_when_raw_data_empty(self, sa_sync_conn):
        # raw_data vide → process_work retourne None et marque processed.
        from sqlalchemy import bindparam, text
        from sqlalchemy.dialects.postgresql import JSONB

        stmt = text("""
            INSERT INTO staging (source, source_id, doi, raw_data, processed)
            VALUES ('crossref', '10.9999/cr-empty', '10.9999/cr-empty', :raw_data, FALSE)
        """).bindparams(bindparam("raw_data", type_=JSONB))
        sa_sync_conn.execute(stmt, {"raw_data": {}})

        processed = _run_normalize_crossref(sa_sync_conn)
        assert processed == 0
        # Le record est tout de même marqué processed pour ne pas être
        # ré-essayé en boucle.
        row = sa_sync_conn.execute(
            text(
                "SELECT processed FROM staging WHERE source = 'crossref' "
                "AND source_id = '10.9999/cr-empty'"
            )
        ).one()
        assert row.processed is True

    def test_skips_when_no_doi(self, sa_sync_conn):
        # raw_data sans DOI → skip avec WARNING + processed=TRUE.
        from sqlalchemy import bindparam, text
        from sqlalchemy.dialects.postgresql import JSONB

        stmt = text("""
            INSERT INTO staging (source, source_id, doi, raw_data, processed)
            VALUES ('crossref', 'no-doi-001', NULL, :raw_data, FALSE)
        """).bindparams(bindparam("raw_data", type_=JSONB))
        sa_sync_conn.execute(stmt, {"raw_data": {"title": ["Untitled"]}})

        processed = _run_normalize_crossref(sa_sync_conn)
        assert processed == 0
        row = sa_sync_conn.execute(
            text(
                "SELECT processed FROM staging WHERE source = 'crossref' "
                "AND source_id = 'no-doi-001'"
            )
        ).one()
        assert row.processed is True

    def test_skips_when_no_title_or_year(self, sa_sync_conn):
        # raw_data avec DOI mais sans titre/année → skip.
        from sqlalchemy import bindparam, text
        from sqlalchemy.dialects.postgresql import JSONB

        stmt = text("""
            INSERT INTO staging (source, source_id, doi, raw_data, processed)
            VALUES ('crossref', '10.9999/no-title', '10.9999/no-title', :raw_data, FALSE)
        """).bindparams(bindparam("raw_data", type_=JSONB))
        sa_sync_conn.execute(stmt, {"raw_data": {"DOI": "10.9999/no-title"}})

        processed = _run_normalize_crossref(sa_sync_conn)
        assert processed == 0
        row = sa_sync_conn.execute(
            text(
                "SELECT processed FROM staging WHERE source = 'crossref' "
                "AND source_id = '10.9999/no-title'"
            )
        ).one()
        assert row.processed is True
