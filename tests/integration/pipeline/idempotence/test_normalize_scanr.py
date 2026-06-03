"""Idempotence : normalisation ScanR."""

from tests.integration.pipeline.idempotence._helpers import create_all_publications

SCANR_STAGING_DOCS = [
    {
        "scanr_id": "doi10.1234/test-article-001",
        "doi": "10.1234/test-article-001",
        "raw_data": {
            "id": "doi10.1234/test-article-001",
            "title": {"default": "A Test Article on Volcanic Eruptions"},
            "year": 2024,
            "type": "journal-article",
            "isOa": True,
            "publicationDate": "2024-03-15T00:00:00",
            "externalIds": [{"type": "doi", "id": "10.1234/test-article-001"}],
            "source": {
                "title": "Journal of Volcanology",
                "publisher": "Elsevier BV",
                "journalIssns": ["0012-3456", "0012-3457"],
                "isOa": False,
                "isInDoaj": False,
            },
            "authors": [
                {
                    "fullName": "Alice Dupont",
                    "role": "author",
                    "person": "idref000000001",
                    "denormalized": {
                        "id": "idref000000001",
                        "idref": "000000001",
                        "orcid": "0000-0001-0001-0001",
                    },
                    "affiliations": [
                        {
                            "name": "Université Clermont Auvergne",
                            "ids": [{"id": "130028061", "type": "siren"}],
                            "detected_countries": ["fr"],
                        },
                    ],
                },
                {
                    "fullName": "Bob Martin",
                    "role": "author",
                    "person": "idref000000002",
                    "denormalized": {"id": "idref000000002", "idref": "000000002"},
                    "affiliations": [
                        {
                            "name": "CNRS",
                            "ids": [{"id": "180089013", "type": "siren"}],
                            "detected_countries": ["fr"],
                        },
                    ],
                },
                {
                    "fullName": "Charlie Noid",
                    "role": "author",
                    "affiliations": [],
                },
            ],
            "affiliations": [
                {"id": "130028061", "label": {"fr": "Université Clermont Auvergne"}},
                {"id": "180089013", "label": {"fr": "CNRS"}},
            ],
        },
    },
    {
        "scanr_id": "doi10.5678/test-chapter-002",
        "doi": "10.5678/test-chapter-002",
        "raw_data": {
            "id": "doi10.5678/test-chapter-002",
            "title": {"default": "A Book Chapter on Climate"},
            "year": 2023,
            "type": "book-chapter",
            "isOa": False,
            "externalIds": [{"type": "doi", "id": "10.5678/test-chapter-002"}],
            "source": {
                "title": "Handbook of Climate Science",
                "publisher": "Springer Nature",
            },
            "authors": [
                {
                    "fullName": "Alice Dupont",
                    "role": "author",
                    "person": "idref000000001",
                    "denormalized": {
                        "id": "idref000000001",
                        "idref": "000000001",
                        "orcid": "0000-0001-0001-0001",
                    },
                    "affiliations": [
                        {
                            "name": "LMV, UCA",
                            "ids": [{"id": "130028061", "type": "siren"}],
                            "detected_countries": ["fr"],
                        },
                    ],
                },
            ],
        },
    },
    {
        "scanr_id": "halhal-09999999",
        "doi": None,
        "raw_data": {
            "id": "halhal-09999999",
            "title": {"default": "Une thèse sur les volcans"},
            "year": 2024,
            "type": "thesis",
            "isOa": True,
            "externalIds": [{"type": "hal", "id": "hal-09999999"}],
            "source": {},
            "authors": [
                {
                    "fullName": "Diana Durand",
                    "role": "author",
                    "affiliations": [
                        {"name": "UCA", "ids": [], "detected_countries": ["fr"]},
                    ],
                },
            ],
        },
    },
]


def insert_scanr_staging(conn, docs):
    """Insère des documents dans staging (source='scanr')."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import JSONB

    stmt = text("""
        INSERT INTO staging (source, source_id, doi, raw_data, processed)
        VALUES ('scanr', :scanr_id, :doi, :raw_data, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET processed = FALSE
    """).bindparams(bindparam("raw_data", type_=JSONB))
    for doc in docs:
        conn.execute(
            stmt, {"scanr_id": doc["scanr_id"], "doi": doc["doi"], "raw_data": doc["raw_data"]}
        )


def _count_tables(conn) -> dict:
    """Retourne les compteurs des tables normalisées."""
    from sqlalchemy import text

    counts = {}
    for t in ("publications", "journals", "publishers"):
        counts[t] = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {t}")).scalar_one()
    counts["scanr_authorships"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_authorships WHERE source = 'scanr'")
    ).scalar_one()
    counts["scanr_documents"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM source_publications WHERE source = 'scanr'")
    ).scalar_one()
    return counts


def run_normalize_scanr(conn):
    """Exécute la normalisation ScanR sur la Connection SA de test."""
    import logging

    from sqlalchemy import text

    from application.pipeline.normalize.normalize_scanr import process_work
    from application.ports.pipeline.staging import StagingRow
    from infrastructure.queries.normalize_authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.normalize_scanr import PgScanrNormalizeQueries
    from infrastructure.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    queries = PgScanrNormalizeQueries()
    staging_queries = PgStagingQueries()
    authorship_queries = PgAuthorshipsBatchQueries()
    logger = logging.getLogger("test")
    journal_repo = journal_repository(conn)
    publisher_repo = publisher_repository(conn)
    pub_repo = publication_repository(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id, doi, raw_data
            FROM staging
            WHERE source = 'scanr' AND processed = FALSE
            ORDER BY id
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


class TestNormalizeScanrIdempotence:
    """La normalisation ScanR produit le même résultat si lancée deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        """Lancer la normalisation deux fois ne crée pas de doublons."""
        from sqlalchemy import text

        insert_scanr_staging(sa_sync_conn, SCANR_STAGING_DOCS)

        # Première passe
        processed_1 = run_normalize_scanr(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_1 = _count_tables(sa_sync_conn)

        assert processed_1 == 3, f"Première passe : {processed_1} traités (attendu 3)"
        assert counts_1["scanr_documents"] == 3
        assert counts_1["publications"] >= 3

        # Reset processed flags
        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'scanr'"))

        # Deuxième passe
        run_normalize_scanr(sa_sync_conn)
        create_all_publications(sa_sync_conn)
        counts_2 = _count_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_author_dedup_by_idref(self, sa_sync_conn):
        """Un même idref sur deux documents → idref porté sur les 2 authorships."""
        from sqlalchemy import text

        insert_scanr_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        run_normalize_scanr(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text(
                "SELECT count(*) AS cnt FROM source_authorships "
                "WHERE source = 'scanr' AND person_identifiers->>'idref' = '000000001'"
            )
        ).scalar_one()
        assert cnt == 2, "Alice devrait avoir 2 authorships (article + chapitre)"

    def test_author_without_idref(self, sa_sync_conn):
        """Un auteur sans idref : authorship sans clé `idref` dans person_identifiers.

        Charlie Noid et Diana Durand n'ont pas d'idref ; ils apparaissent
        dans `source_authorships` sans `idref` dans `person_identifiers`.
        L'identité sera reconstruite au pipeline `personnes` via les name_forms.
        """
        from sqlalchemy import text

        insert_scanr_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        run_normalize_scanr(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("""
                SELECT count(*) AS cnt FROM source_authorships
                WHERE source = 'scanr'
                  AND (person_identifiers->>'idref') IS NULL
                  AND raw_author_name IN ('Charlie Noid', 'Diana Durand')
            """)
        ).scalar_one()
        assert cnt == 2

    def test_publication_dedup_by_doi(self, sa_sync_conn):
        """Deux documents ScanR avec le même DOI → une seule publication."""
        from sqlalchemy import text

        dup = {
            "scanr_id": "doi10.1234/test-article-001-bis",
            "doi": "10.1234/test-article-001",
            "raw_data": {
                "id": "doi10.1234/test-article-001-bis",
                "title": {"default": "A Test Article on Volcanic Eruptions"},
                "year": 2024,
                "type": "journal-article",
                "isOa": True,
                "externalIds": [{"type": "doi", "id": "10.1234/test-article-001"}],
                "source": {"title": "Journal of Volcanology", "publisher": "Elsevier BV"},
                "authors": [],
            },
        }
        insert_scanr_staging(sa_sync_conn, SCANR_STAGING_DOCS + [dup])
        run_normalize_scanr(sa_sync_conn)
        create_all_publications(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text(
                "SELECT count(*) AS cnt FROM publications "
                "WHERE lower(doi) = '10.1234/test-article-001'"
            )
        ).scalar_one()
        assert cnt == 1, "Le DOI devrait être dédupliqué"

        cnt = sa_sync_conn.execute(
            text("SELECT count(*) AS cnt FROM source_publications WHERE source = 'scanr'")
        ).scalar_one()
        assert cnt == 4, "4 scanr_documents (3 originaux + 1 bis)"

    def test_journal_dedup(self, sa_sync_conn):
        """Deux documents avec le même journal → un seul journal."""
        from sqlalchemy import text

        insert_scanr_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        run_normalize_scanr(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("SELECT count(*) AS cnt FROM journals WHERE title_normalized LIKE '%volcanology%'")
        ).scalar_one()
        assert cnt == 1

    def test_publisher_dedup(self, sa_sync_conn):
        """Le même éditeur n'est pas créé en double."""
        from sqlalchemy import text

        insert_scanr_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        run_normalize_scanr(sa_sync_conn)

        # Première passe ok, reset et relance
        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'scanr'"))
        run_normalize_scanr(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("SELECT count(*) AS cnt FROM publishers WHERE name_normalized LIKE '%elsevier%'")
        ).scalar_one()
        assert cnt == 1, "Elsevier BV ne devrait exister qu'une fois"
