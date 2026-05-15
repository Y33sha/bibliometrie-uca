"""
Tests d'idempotence des phases de normalisation.

Principe : insérer des données de staging, lancer la normalisation,
compter les résultats, relancer, vérifier que les compteurs n'ont pas bougé.

Ces tests tournent sur la base bibliometrie_test (cf. conftest.py).
"""

from domain.normalize import normalize_text
from domain.publication import normalize_nnt
from domain.publications.doc_types import map_doc_type
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from infrastructure.repositories import publication_repository
from tests.integration.helpers.publications import (
    find_or_create_for_tests as find_or_create_publication,
)


def _create_all_publications(conn_or_cur):
    """Crée les publications pour tous les source_publications orphelins.

    Simule la phase 'publications' du pipeline dans les tests. Dispatche
    selon le type (cur psycopg | Connection SA), le temps que tous les
    tests pipeline soient migrés en SA.
    """
    from sqlalchemy import Connection, text

    repo = publication_repository(conn_or_cur)
    if isinstance(conn_or_cur, Connection):
        rows = conn_or_cur.execute(
            text("""
                SELECT id, source, doi, title, pub_year, doc_type, journal_id,
                       oa_status, language, container_title, external_ids
                FROM source_publications WHERE publication_id IS NULL
                ORDER BY id
            """)
        ).all()
        docs = [dict(r._mapping) for r in rows]
    else:
        conn_or_cur.execute("""
            SELECT id, source, doi, title, pub_year, doc_type, journal_id,
                   oa_status, language, container_title, external_ids
            FROM source_publications WHERE publication_id IS NULL
            ORDER BY id
        """)
        docs = list(conn_or_cur.fetchall())

    for doc in docs:
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
        candidate = Publication(
            id=None,
            title=title,
            title_normalized=normalize_text(title),
            pub_year=pub_year,
            doc_type=doc_type,
            doi=DOI(doc["doi"]) if doc["doi"] else None,
            oa_status=doc["oa_status"] or "unknown",
            journal_id=doc["journal_id"],
            container_title=doc["container_title"],
            language=doc["language"],
        )
        result, _ = find_or_create_publication(candidate, nnt=nnt, allow_create=True, repo=repo)
        if result and result.id is not None:
            if isinstance(conn_or_cur, Connection):
                conn_or_cur.execute(
                    text("UPDATE source_publications SET publication_id = :pid WHERE id = :sid"),
                    {"pid": result.id, "sid": doc["id"]},
                )
            else:
                conn_or_cur.execute(
                    "UPDATE source_publications SET publication_id = %s WHERE id = %s",
                    (result.id, doc["id"]),
                )
            repo.update_sources(result.id)


# ── Fixtures de données ScanR ────────────────────────────────────

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


def _insert_staging(conn, docs):
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


def _run_normalize_scanr(conn):
    """Exécute la normalisation ScanR sur la Connection SA de test."""
    import logging

    from sqlalchemy import text

    from application.pipeline.normalize.normalize_scanr import process_work
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.db.queries.normalize_scanr import PgScanrNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    queries = PgScanrNormalizeQueries()
    staging_queries = PgStagingQueries()
    address_linker = PgAddressLinker()
    logger = logging.getLogger("test")
    journal_repo = journal_repository(conn)
    publisher_repo = publisher_repository(conn)
    pub_repo = publication_repository(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id AS scanr_id, doi, raw_data
            FROM staging
            WHERE source = 'scanr' AND processed = FALSE
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
            staging_queries=staging_queries,
            address_linker=address_linker,
        ):
            processed += 1
    return processed


# ── Tests ────────────────────────────────────────────────────────


class TestNormalizeScanrIdempotence:
    """La normalisation ScanR produit le même résultat si lancée deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        """Lancer la normalisation deux fois ne crée pas de doublons."""
        from sqlalchemy import text

        _insert_staging(sa_sync_conn, SCANR_STAGING_DOCS)

        # Première passe
        processed_1 = _run_normalize_scanr(sa_sync_conn)
        _create_all_publications(sa_sync_conn)
        counts_1 = _count_tables(sa_sync_conn)

        assert processed_1 == 3, f"Première passe : {processed_1} traités (attendu 3)"
        assert counts_1["scanr_documents"] == 3
        assert counts_1["publications"] >= 3

        # Reset processed flags
        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'scanr'"))

        # Deuxième passe
        _run_normalize_scanr(sa_sync_conn)
        _create_all_publications(sa_sync_conn)
        counts_2 = _count_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_author_dedup_by_idref(self, sa_sync_conn):
        """Un même idref sur deux documents → idref porté sur les 2 authorships."""
        from sqlalchemy import text

        _insert_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        _run_normalize_scanr(sa_sync_conn)

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

        _insert_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        _run_normalize_scanr(sa_sync_conn)

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
        _insert_staging(sa_sync_conn, SCANR_STAGING_DOCS + [dup])
        _run_normalize_scanr(sa_sync_conn)
        _create_all_publications(sa_sync_conn)

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

        _insert_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        _run_normalize_scanr(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("SELECT count(*) AS cnt FROM journals WHERE title_normalized LIKE '%volcanology%'")
        ).scalar_one()
        assert cnt == 1

    def test_publisher_dedup(self, sa_sync_conn):
        """Le même éditeur n'est pas créé en double."""
        from sqlalchemy import text

        _insert_staging(sa_sync_conn, SCANR_STAGING_DOCS)
        _run_normalize_scanr(sa_sync_conn)

        # Première passe ok, reset et relance
        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'scanr'"))
        _run_normalize_scanr(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("SELECT count(*) AS cnt FROM publishers WHERE name_normalized LIKE '%elsevier%'")
        ).scalar_one()
        assert cnt == 1, "Elsevier BV ne devrait exister qu'une fois"


# ══════════════════════════════════════════════════════════════════
# HAL
# ══════════════════════════════════════════════════════════════════

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


def _insert_hal_staging(conn, docs):
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


def _run_normalize_hal(conn):
    """Exécute la normalisation HAL sur la Connection SA de test."""
    import logging

    from sqlalchemy import text

    from application.pipeline.normalize.normalize_hal import process_work
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.db.queries.normalize_hal import PgHalNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )
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

        _insert_hal_staging(sa_sync_conn, HAL_STAGING_DOCS)

        processed_1 = _run_normalize_hal(sa_sync_conn)
        counts_1 = _count_hal_tables(sa_sync_conn)
        assert processed_1 == 3

        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'hal'"))
        _run_normalize_hal(sa_sync_conn)
        counts_2 = _count_hal_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )


# ══════════════════════════════════════════════════════════════════
# OpenAlex
# ══════════════════════════════════════════════════════════════════

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


def _insert_oa_staging(conn, docs):
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


def _run_normalize_oa(conn):
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
        _insert_oa_staging(sa_sync_conn, OA_STAGING_DOCS)

        processed_1 = _run_normalize_oa(sa_sync_conn)
        _create_all_publications(sa_sync_conn)
        counts_1 = _count_oa_tables(sa_sync_conn)
        assert processed_1 == 3

        # Réinjecter le raw_data (vidé par le normaliseur) et relancer
        _insert_oa_staging(sa_sync_conn, OA_STAGING_DOCS)
        _run_normalize_oa(sa_sync_conn)
        _create_all_publications(sa_sync_conn)
        counts_2 = _count_oa_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )


# ══════════════════════════════════════════════════════════════════
# WoS
# ══════════════════════════════════════════════════════════════════

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


def _insert_wos_staging(conn, docs):
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import JSONB

    stmt = text("""
        INSERT INTO staging (source, source_id, doi, raw_data, processed)
        VALUES ('wos', :ut, :doi, :raw_data, FALSE)
        ON CONFLICT (source, source_id) DO UPDATE SET processed = FALSE
    """).bindparams(bindparam("raw_data", type_=JSONB))
    for doc in docs:
        conn.execute(stmt, {"ut": doc["ut"], "doi": doc["doi"], "raw_data": doc["raw_data"]})


def _run_normalize_wos(conn):
    import logging

    from sqlalchemy import text

    from application.pipeline.normalize.normalize_wos import process_record
    from infrastructure.db.queries.normalize_wos import PgWosNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    queries = PgWosNormalizeQueries()
    staging_queries = PgStagingQueries()
    logger = logging.getLogger("test")
    journal_repo = journal_repository(conn)
    publisher_repo = publisher_repository(conn)
    pub_repo = publication_repository(conn)

    rows = conn.execute(
        text("""
            SELECT id, source_id AS ut, doi, raw_data
            FROM staging WHERE source = 'wos' AND processed = FALSE ORDER BY id
        """)
    ).all()
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

        _insert_wos_staging(sa_sync_conn, WOS_STAGING_DOCS)

        processed_1 = _run_normalize_wos(sa_sync_conn)
        counts_1 = _count_wos_tables(sa_sync_conn)
        assert processed_1 == 3

        sa_sync_conn.execute(text("UPDATE staging SET processed = FALSE WHERE source = 'wos'"))
        _run_normalize_wos(sa_sync_conn)
        counts_2 = _count_wos_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )


# ══════════════════════════════════════════════════════════════════
# Inter-sources
# ══════════════════════════════════════════════════════════════════

SHARED_DOI = "10.9999/shared-article-001"

INTER_HAL_DOCS = [
    {
        "halid": "hal-99100001",
        "doi": SHARED_DOI,
        "hal_collections": ["TEST"],
        "raw_data": {
            "docType_s": "ART",
            "title_s": ["Shared Article on Geochemistry"],
            "producedDateY_i": 2024,
            "doiId_s": SHARED_DOI,
            "journalTitle_s": "Geochemistry International",
            "journalIssn_s": "5555-6666",
            "journalPublisher_s": "Geochem Press",
            "authFullName_s": ["Alice Dupont", "Bob Martin"],
            "openAccess_bool": True,
        },
    },
    {
        "halid": "hal-99100002",
        "doi": None,
        "hal_collections": ["TEST"],
        "raw_data": {
            "docType_s": "REPORT",
            "title_s": ["Un rapport sans DOI"],
            "producedDateY_i": 2024,
            "authFullName_s": ["Alice Dupont"],
        },
    },
]

INTER_OA_DOCS = [
    {
        "openalex_id": "W9910000001",
        "doi": SHARED_DOI,
        "raw_data": {
            "id": "https://openalex.org/W9910000001",
            "doi": f"https://doi.org/{SHARED_DOI}",
            "title": "Shared Article on Geochemistry",
            "display_name": "Shared Article on Geochemistry",
            "publication_year": 2024,
            "type": "article",
            "language": "en",
            "primary_location": {
                "source": {
                    "display_name": "Geochemistry International",
                    "type": "journal",
                    "issn": ["5555-6666"],
                    "host_organization_name": "Geochem Press",
                },
            },
            "authorships": [
                {
                    "author": {
                        "id": "https://openalex.org/A991001",
                        "display_name": "Alice Dupont",
                    },
                    "author_position": "first",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
                {
                    "author": {"id": "https://openalex.org/A991002", "display_name": "Bob Martin"},
                    "author_position": "last",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
            ],
            "open_access": {"oa_status": "gold", "is_oa": True},
            "cited_by_count": 3,
        },
    },
    {
        "openalex_id": "W9910000002",
        "doi": None,
        "raw_data": {
            "id": "https://openalex.org/W9910000002",
            "title": "Another OA-only Article",
            "display_name": "Another OA-only Article",
            "publication_year": 2024,
            "type": "article",
            "primary_location": {"source": None},
            "authorships": [
                {
                    "author": {
                        "id": "https://openalex.org/A991003",
                        "display_name": "Charlie Noid",
                    },
                    "author_position": "first",
                    "institutions": [],
                    "raw_affiliation_strings": [],
                },
            ],
            "open_access": {"oa_status": "closed", "is_oa": False},
        },
    },
]


class TestNormalizeInterSourceIdempotence:
    """Normaliser HAL puis OA puis relancer HAL ne crée pas de doublons."""

    def test_hal_then_oa_then_hal_again(self, sa_sync_conn):
        from sqlalchemy import text

        _insert_hal_staging(sa_sync_conn, INTER_HAL_DOCS)
        _insert_oa_staging(sa_sync_conn, INTER_OA_DOCS)

        # Passe 1 : HAL
        _run_normalize_hal(sa_sync_conn)
        _create_all_publications(sa_sync_conn)
        pubs_after_hal = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications")
        ).scalar_one()

        # Passe 2 : OA
        _run_normalize_oa(sa_sync_conn)
        _create_all_publications(sa_sync_conn)
        pubs_after_oa = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications")
        ).scalar_one()

        # L'article partagé ne doit pas être dupliqué (même DOI)
        cnt = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications WHERE lower(doi) = lower(:doi)"),
            {"doi": SHARED_DOI},
        ).scalar_one()
        assert cnt == 1, "L'article partagé ne doit exister qu'une fois"

        # Le rapport HAL sans DOI + l'article OA-only = 2 pubs de plus
        assert pubs_after_oa == pubs_after_hal + 1, (
            f"OA devrait ajouter 1 pub (OA-only), pas plus. "
            f"HAL={pubs_after_hal}, après OA={pubs_after_oa}"
        )

        # Passe 3 : relancer HAL
        _insert_hal_staging(sa_sync_conn, INTER_HAL_DOCS)
        _run_normalize_hal(sa_sync_conn)
        pubs_after_hal2 = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS cnt FROM publications")
        ).scalar_one()

        assert pubs_after_hal2 == pubs_after_oa, (
            f"Relancer HAL ne devrait rien créer. Avant={pubs_after_oa}, après={pubs_after_hal2}"
        )

    def test_shared_doi_same_journal(self, sa_sync_conn):
        """L'article partagé pointe vers le même journal, pas un doublon."""
        from sqlalchemy import text

        _insert_hal_staging(sa_sync_conn, INTER_HAL_DOCS)
        _insert_oa_staging(sa_sync_conn, INTER_OA_DOCS)

        _run_normalize_hal(sa_sync_conn)
        _run_normalize_oa(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("""
                SELECT COUNT(*) AS cnt FROM journals
                WHERE title_normalized LIKE '%geochemistry international%'
            """)
        ).scalar_one()
        assert cnt == 1, "Le journal partagé ne doit exister qu'une fois"


# ══════════════════════════════════════════════════════════════════
# create_persons_from_source_authorships
# ══════════════════════════════════════════════════════════════════


def _setup_persons_test_data(conn):
    """Crée une chaîne complète de données pour tester create_persons :
    publications → source_publications (hal) → source_authorships (in_perimeter=TRUE).
    """
    from sqlalchemy import text

    # Publications
    conn.execute(
        text("""
            INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
            VALUES (90001, 'Test Pub Alpha', 'test pub alpha', 'article', 2024),
                   (90002, 'Test Pub Beta', 'test pub beta', 'thesis', 2024)
        """)
    )

    # HAL documents
    conn.execute(
        text("""
            INSERT INTO source_publications (id, source, source_id, title, pub_year, doc_type, publication_id)
            VALUES (90001, 'hal', 'hal-90000001', 'Test Pub Alpha', 2024, 'ART', 90001),
                   (90002, 'hal', 'hal-90000002', 'Test Pub Beta', 2024, 'THESE', 90002)
        """)
    )

    # HAL authorships — `person_identifiers` porte orcid + hal_person_id par
    # observation. Eve Leroy (hal_person_id=900001, orcid renseigné) apparaît
    # sur les 2 pubs. Frank Moreau (hal_person_id=900002) sur la pub 90001.
    # Grace Petit (sans identifiant) sur la pub 90002.
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position, in_perimeter,
                 person_id, author_name_normalized, raw_author_name, person_identifiers)
            VALUES
                (90001, 'hal', 90001, 0, TRUE, NULL, 'eve leroy', 'Eve Leroy',
                 '{"orcid": "0000-0001-9999-0001", "hal_person_id": 900001}'),
                (90002, 'hal', 90001, 1, TRUE, NULL, 'frank moreau', 'Frank Moreau',
                 '{"hal_person_id": 900002}'),
                (90003, 'hal', 90002, 0, TRUE, NULL, 'eve leroy', 'Eve Leroy',
                 '{"orcid": "0000-0001-9999-0001", "hal_person_id": 900001}'),
                (90004, 'hal', 90002, 1, TRUE, NULL, 'grace petit', 'Grace Petit', NULL)
        """)
    )


def _run_create_persons(conn):
    """Exécute create_persons sur la Connection SA de test, retourne le
    nombre d'authorships HAL rattachées à l'issue du run."""
    import logging

    from sqlalchemy import text

    from application.pipeline.persons.create_persons_from_source_authorships import run
    from infrastructure.db.queries.persons.create import PgPersonsCreateQueries
    from infrastructure.repositories import person_repository

    queries = PgPersonsCreateQueries()
    logger = logging.getLogger("test")
    run(conn, queries, logger, person_repo=person_repository(conn))

    return conn.execute(
        text(
            "SELECT COUNT(*) FROM source_authorships WHERE source = 'hal' AND person_id IS NOT NULL"
        )
    ).scalar_one()


def _count_persons_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for t in ("persons", "person_name_forms", "person_identifiers"):
        counts[t] = conn.execute(text(f"SELECT COUNT(*) AS cnt FROM {t}")).scalar_one()
    counts["hal_as_linked"] = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM source_authorships "
            "WHERE source = 'hal' AND person_id IS NOT NULL"
        )
    ).scalar_one()
    return counts


class TestCreatePersonsIdempotence:
    """create_persons produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        from sqlalchemy import text

        _setup_persons_test_data(sa_sync_conn)

        # Passe 1
        linked_1 = _run_create_persons(sa_sync_conn)
        counts_1 = _count_persons_tables(sa_sync_conn)

        assert linked_1 == 4, f"4 authorships à rattacher, got {linked_1}"
        assert counts_1["hal_as_linked"] == 4

        # Reset : remettre person_id à NULL sur les authorships
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET person_id = NULL WHERE source = 'hal'")
        )

        # Passe 2
        _run_create_persons(sa_sync_conn)
        counts_2 = _count_persons_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_same_hal_person_id_one_person(self, sa_sync_conn):
        """Deux authorships avec le même hal_person_id → une seule personne."""
        from sqlalchemy import text

        _setup_persons_test_data(sa_sync_conn)
        _run_create_persons(sa_sync_conn)

        # Eve Leroy (hal_person_id=900001) apparaît sur 2 documents
        rows = sa_sync_conn.execute(
            text("""
                SELECT DISTINCT person_id FROM source_authorships
                WHERE source = 'hal'
                  AND person_identifiers->>'hal_person_id' = '900001'
                  AND person_id IS NOT NULL
            """)
        ).all()
        assert len(rows) == 1, "Eve Leroy devrait être une seule personne"

    def test_orcid_registered(self, sa_sync_conn):
        """L'ORCID d'Eve Leroy est enregistré dans person_identifiers."""
        from sqlalchemy import text

        _setup_persons_test_data(sa_sync_conn)
        _run_create_persons(sa_sync_conn)

        cnt = sa_sync_conn.execute(
            text("""
                SELECT COUNT(*) AS cnt FROM person_identifiers
                WHERE id_type = 'orcid' AND id_value = '0000-0001-9999-0001'
            """)
        ).scalar_one()
        assert cnt == 1


# ══════════════════════════════════════════════════════════════════
# build_authorships
# ══════════════════════════════════════════════════════════════════


def _run_build_authorships(conn):
    """Exécute build_authorships sur la Connection SA de test."""
    import logging

    from application.pipeline.authorships.build_authorships import build
    from infrastructure.db.queries.authorships_build import PgAuthorshipsBuildQueries

    build(conn, PgAuthorshipsBuildQueries(), logging.getLogger("test"))


def _count_authorships_tables(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    counts["total"] = conn.execute(text("SELECT COUNT(*) AS cnt FROM authorships")).scalar_one()
    counts["in_perimeter"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM authorships WHERE in_perimeter = TRUE")
    ).scalar_one()
    counts["hal_fk"] = conn.execute(
        text(
            "SELECT COUNT(*) AS cnt FROM source_authorships "
            "WHERE authorship_id IS NOT NULL AND source = 'hal'"
        )
    ).scalar_one()
    counts["with_structs"] = conn.execute(
        text("SELECT COUNT(*) AS cnt FROM authorships WHERE structure_ids IS NOT NULL")
    ).scalar_one()
    return counts


class TestBuildAuthorshipsIdempotence:
    """build_authorships produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        _setup_persons_test_data(sa_sync_conn)
        _run_create_persons(sa_sync_conn)

        _run_build_authorships(sa_sync_conn)
        counts_1 = _count_authorships_tables(sa_sync_conn)

        assert counts_1["total"] >= 3, f"Au moins 3 authorships, got {counts_1['total']}"
        assert counts_1["hal_fk"] >= 3, "Les FK HAL doivent être peuplées"

        _run_build_authorships(sa_sync_conn)
        counts_2 = _count_authorships_tables(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )


# ══════════════════════════════════════════════════════════════════
# populate_affiliations
# ══════════════════════════════════════════════════════════════════


def _setup_affiliations_test_data(conn):
    """Crée des données pour tester populate_affiliations :
    structures + périmètres + adresses + source_authorships liées.

    Scénario : une structure UCA (labo, id=80001) avec une relation
    est_tutelle_de → UCA (id=80000). Un authorship OpenAlex est rattaché
    au labo via une adresse résolue. Un authorship HAL coexiste sans
    résolution d'adresse (sert pour l'idempotence des comptages).
    """
    from sqlalchemy import text

    conn.execute(
        text("""
            INSERT INTO config (key, value) VALUES
                ('perimeter_affiliations', '"uca_wide"'),
                ('perimeter_persons', '"uca"')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """)
    )

    conn.execute(
        text("""
            INSERT INTO perimeters (code, name, structure_ids) VALUES
                ('uca', 'UCA restreint', ARRAY[80000]),
                ('uca_wide', 'UCA large', ARRAY[80000])
            ON CONFLICT (code) DO UPDATE SET structure_ids = EXCLUDED.structure_ids
        """)
    )

    conn.execute(
        text("""
            INSERT INTO structures (id, code, name, acronym, structure_type)
            VALUES (80000, 'UCA', 'Université Clermont Auvergne', 'UCA', 'universite'),
                   (80001, 'LABO-TEST', 'Laboratoire Test', 'LT', 'labo')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO structure_relations (parent_id, child_id, relation_type)
            VALUES (80000, 80001, 'est_tutelle_de')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
            VALUES (80001, 'Pub Affiliation Test', 'pub affiliation test', 'article', 2024)
        """)
    )

    conn.execute(
        text("""
            INSERT INTO source_publications (id, source, source_id, title, pub_year, doc_type, publication_id)
            VALUES (80001, 'hal', 'hal-80000001', 'Pub Affiliation Test', 2024, 'ART', 80001),
                   (80002, 'openalex', 'W80000001', 'Pub Affiliation Test', 2024, 'article', 80001)
        """)
    )

    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position,
                 in_perimeter, author_name_normalized)
            VALUES (80001, 'hal', 80001, 0, FALSE, 'alice dupont')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position,
                 in_perimeter, author_name_normalized)
            VALUES (80002, 'openalex', 80002, 0, FALSE, 'alice dupont')
        """)
    )

    conn.execute(
        text("""
            INSERT INTO addresses (id, raw_text, normalized_text)
            VALUES (80001, 'Laboratoire Test, UCA, Clermont-Ferrand', 'laboratoire test uca clermont ferrand')
        """)
    )
    conn.execute(
        text("""
            INSERT INTO address_structures (address_id, structure_id, is_confirmed)
            VALUES (80001, 80001, TRUE)
        """)
    )
    conn.execute(
        text("""
            INSERT INTO source_authorship_addresses (source_authorship_id, address_id)
            VALUES (80002, 80001)
        """)
    )


def _run_populate_affiliations(conn):
    """Exécute populate_affiliations sur la Connection SA de test."""
    import logging

    from application.pipeline.affiliations.populate_affiliations import (
        _step_address_source,
        step3d_theses,
    )
    from infrastructure.db.queries.affiliations import PgAffiliationsQueries
    from infrastructure.perimeter import get_affiliations_structure_ids, get_persons_structure_ids

    perimeter_ids = get_persons_structure_ids(conn)
    wide_ids = get_affiliations_structure_ids(conn)
    queries = PgAffiliationsQueries()
    logger = logging.getLogger("test")

    for source in ["hal", "openalex", "wos", "scanr"]:
        _step_address_source(conn, queries, logger, source, perimeter_ids, wide_ids)
    step3d_theses(conn, queries, logger, wide_ids)


def _count_affiliations(conn) -> dict:
    from sqlalchemy import text

    counts = {}
    for src in ["hal", "openalex"]:
        counts[f"{src}_in_perimeter"] = conn.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM source_authorships "
                "WHERE source = :src AND in_perimeter = TRUE"
            ),
            {"src": src},
        ).scalar_one()
        counts[f"{src}_with_structs"] = conn.execute(
            text(
                "SELECT COUNT(*) AS cnt FROM source_authorships "
                "WHERE source = :src AND structure_ids IS NOT NULL"
            ),
            {"src": src},
        ).scalar_one()
    return counts


class TestPopulateAffiliationsIdempotence:
    """populate_affiliations produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, sa_sync_conn):
        _setup_affiliations_test_data(sa_sync_conn)

        _run_populate_affiliations(sa_sync_conn)
        counts_1 = _count_affiliations(sa_sync_conn)

        # HAL utilise maintenant le circuit adresses (comme les autres sources).
        # Sans populate_addresses + resolve_addresses dans ce test, HAL n'est pas in_perimeter.
        # L'idempotence est vérifiée par la comparaison counts_1 == counts_2 ci-dessous.
        assert counts_1["openalex_in_perimeter"] == 1, "L'authorship OA doit être in_perimeter"
        assert counts_1["openalex_with_structs"] == 1, (
            "L'authorship OA doit avoir des structure_ids"
        )

        _run_populate_affiliations(sa_sync_conn)
        counts_2 = _count_affiliations(sa_sync_conn)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_run_populate_is_source_agnostic(self, sa_sync_conn):
        """Régression : run_populate doit traiter toutes les sources sans filtre.

        Une weekly avec --sources=hal ne doit plus laisser les SAs OpenAlex
        bloquées sans structure_ids quand leur adresse a été résolue entre
        deux runs (cas observé sur pub 21743 : adresse UCA résolue mais
        Marc Ruivard / Olivier Aumaître côté OA restés sans structure_ids
        car la weekly run ne ciblait que hal+scanr).
        """
        import logging

        from sqlalchemy import text

        from application.pipeline.affiliations.populate_affiliations import run_populate
        from infrastructure.db.queries.affiliations import PgAffiliationsQueries
        from infrastructure.perimeter import (
            get_affiliations_structure_ids,
            get_persons_structure_ids,
        )

        _setup_affiliations_test_data(sa_sync_conn)

        run_populate(
            sa_sync_conn,
            PgAffiliationsQueries(),
            logging.getLogger("test"),
            get_persons_structure_ids(sa_sync_conn),
            get_affiliations_structure_ids(sa_sync_conn),
        )

        row = sa_sync_conn.execute(
            text("SELECT in_perimeter, structure_ids FROM source_authorships WHERE id = 80002")
        ).one()
        assert row.in_perimeter is True
        assert row.structure_ids == [80001]
