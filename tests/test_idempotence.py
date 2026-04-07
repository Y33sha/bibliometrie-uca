"""
Tests d'idempotence des phases de normalisation.

Principe : insérer des données de staging, lancer la normalisation,
compter les résultats, relancer, vérifier que les compteurs n'ont pas bougé.

Ces tests tournent sur la base bibliometrie_test (cf. conftest.py).
"""

import json
import pytest
from psycopg2.extras import Json


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
                    "denormalized": {"id": "idref000000001", "idref": "000000001", "orcid": "0000-0001-0001-0001"},
                    "affiliations": [
                        {"name": "Université Clermont Auvergne", "ids": [{"id": "130028061", "type": "siren"}], "detected_countries": ["fr"]},
                    ],
                },
                {
                    "fullName": "Bob Martin",
                    "role": "author",
                    "person": "idref000000002",
                    "denormalized": {"id": "idref000000002", "idref": "000000002"},
                    "affiliations": [
                        {"name": "CNRS", "ids": [{"id": "180089013", "type": "siren"}], "detected_countries": ["fr"]},
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
                    "denormalized": {"id": "idref000000001", "idref": "000000001", "orcid": "0000-0001-0001-0001"},
                    "affiliations": [
                        {"name": "LMV, UCA", "ids": [{"id": "130028061", "type": "siren"}], "detected_countries": ["fr"]},
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


def _insert_staging(cur, docs):
    """Insère des documents dans staging_scanr."""
    for doc in docs:
        cur.execute("""
            INSERT INTO staging_scanr (scanr_id, doi, raw_data, processed)
            VALUES (%s, %s, %s, FALSE)
            ON CONFLICT (scanr_id) DO UPDATE SET processed = FALSE
        """, (doc["scanr_id"], doc["doi"], Json(doc["raw_data"])))


def _count_tables(cur) -> dict:
    """Retourne les compteurs des tables normalisées."""
    tables = [
        "publications", "journals", "publishers",
        "scanr_documents", "scanr_authors", "scanr_authorships",
    ]
    counts = {}
    for t in tables:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {t}")
        counts[t] = cur.fetchone()["cnt"]
    return counts


def _run_normalize_scanr(cur):
    """Exécute la normalisation ScanR sur le curseur de test."""
    from processing.normalize_scanr import process_work

    cur.execute("""
        SELECT id, scanr_id, doi, raw_data
        FROM staging_scanr
        WHERE processed = FALSE
        ORDER BY id
    """)
    rows = cur.fetchall()
    processed = 0
    for row in rows:
        if process_work(cur, row):
            processed += 1
    return processed


# ── Tests ────────────────────────────────────────────────────────


class TestNormalizeScanrIdempotence:
    """La normalisation ScanR produit le même résultat si lancée deux fois."""

    def test_double_run_same_counts(self, db):
        """Lancer la normalisation deux fois ne crée pas de doublons."""
        _insert_staging(db, SCANR_STAGING_DOCS)

        # Première passe
        processed_1 = _run_normalize_scanr(db)
        counts_1 = _count_tables(db)

        assert processed_1 == 3, f"Première passe : {processed_1} traités (attendu 3)"
        assert counts_1["scanr_documents"] == 3
        assert counts_1["scanr_authors"] >= 3  # Alice apparaît 2 fois mais dédupliquée par idref
        assert counts_1["publications"] >= 3

        # Reset processed flags
        db.execute("UPDATE staging_scanr SET processed = FALSE")

        # Deuxième passe
        processed_2 = _run_normalize_scanr(db)
        counts_2 = _count_tables(db)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n"
            f"  1ère : {counts_1}\n"
            f"  2ème : {counts_2}"
        )

    def test_author_dedup_by_idref(self, db):
        """Un même idref sur deux documents → un seul scanr_author."""
        _insert_staging(db, SCANR_STAGING_DOCS)
        _run_normalize_scanr(db)

        db.execute("SELECT count(*) AS cnt FROM scanr_authors WHERE idref = '000000001'")
        assert db.fetchone()["cnt"] == 1, "Alice Dupont devrait être dédupliquée par idref"

        db.execute("SELECT count(*) AS cnt FROM scanr_authorships WHERE scanr_author_id = (SELECT id FROM scanr_authors WHERE idref = '000000001')")
        assert db.fetchone()["cnt"] == 2, "Alice devrait avoir 2 authorships (article + chapitre)"

    def test_author_without_idref(self, db):
        """Un auteur sans idref est créé sans doublon."""
        _insert_staging(db, SCANR_STAGING_DOCS)
        _run_normalize_scanr(db)

        db.execute("SELECT count(*) AS cnt FROM scanr_authors WHERE idref IS NULL")
        count = db.fetchone()["cnt"]
        assert count >= 2, "Charlie Noid et Diana Durand n'ont pas d'idref"

    def test_publication_dedup_by_doi(self, db):
        """Deux documents ScanR avec le même DOI → une seule publication."""
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
        _insert_staging(db, SCANR_STAGING_DOCS + [dup])
        _run_normalize_scanr(db)

        db.execute("SELECT count(*) AS cnt FROM publications WHERE lower(doi) = '10.1234/test-article-001'")
        assert db.fetchone()["cnt"] == 1, "Le DOI devrait être dédupliqué"

        db.execute("SELECT count(*) AS cnt FROM scanr_documents")
        assert db.fetchone()["cnt"] == 4, "4 scanr_documents (3 originaux + 1 bis)"

    def test_journal_dedup(self, db):
        """Deux documents avec le même journal → un seul journal."""
        _insert_staging(db, SCANR_STAGING_DOCS)
        _run_normalize_scanr(db)

        db.execute("SELECT count(*) AS cnt FROM journals WHERE title_normalized LIKE '%volcanology%'")
        assert db.fetchone()["cnt"] == 1

    def test_publisher_dedup(self, db):
        """Le même éditeur n'est pas créé en double."""
        _insert_staging(db, SCANR_STAGING_DOCS)
        _run_normalize_scanr(db)

        # Première passe ok, reset et relance
        db.execute("UPDATE staging_scanr SET processed = FALSE")
        _run_normalize_scanr(db)

        db.execute("SELECT count(*) AS cnt FROM publishers WHERE name_normalized LIKE '%elsevier%'")
        assert db.fetchone()["cnt"] == 1, "Elsevier BV ne devrait exister qu'une fois"


# ══════════════════════════════════════════════════════════════════
# HAL
# ══════════════════════════════════════════════════════════════════

HAL_STAGING_DOCS = [
    {
        "halid": "hal-99000001",
        "doi": "10.9999/hal-test-001",
        "collection": "TEST",
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
        "collection": "TEST",
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
        "collection": "TEST",
        "raw_data": {
            "docType_s": "THESE",
            "title_s": ["Une thèse sans DOI sur la géologie"],
            "producedDateY_i": 2024,
            "authFullName_s": ["Grace Petit"],
        },
    },
]


def _insert_hal_staging(cur, docs):
    for doc in docs:
        cur.execute("""
            INSERT INTO staging_hal (halid, doi, raw_data, collection, processed)
            VALUES (%s, %s, %s, %s, FALSE)
            ON CONFLICT (halid) DO UPDATE SET processed = FALSE
        """, (doc["halid"], doc["doi"], Json(doc["raw_data"]), doc["collection"]))


def _run_normalize_hal(cur):
    """Exécute la normalisation HAL via un curseur tuple (comme le vrai script)."""
    plain_cur = cur.connection.cursor()
    from processing.normalize_hal import process_work
    plain_cur.execute("""
        SELECT id, halid, doi, raw_data, collection
        FROM staging_hal WHERE processed = FALSE ORDER BY id
    """)
    rows = plain_cur.fetchall()
    processed = 0
    for row in rows:
        if process_work(plain_cur, row):
            processed += 1
    return processed


def _count_hal_tables(cur) -> dict:
    counts = {}
    for t in ["publications", "hal_documents", "hal_authors", "hal_authorships"]:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {t}")
        counts[t] = cur.fetchone()["cnt"]
    return counts


class TestNormalizeHalIdempotence:
    def test_double_run_same_counts(self, db):
        _insert_hal_staging(db, HAL_STAGING_DOCS)

        processed_1 = _run_normalize_hal(db)
        counts_1 = _count_hal_tables(db)
        assert processed_1 == 3

        db.execute("UPDATE staging_hal SET processed = FALSE")
        _run_normalize_hal(db)
        counts_2 = _count_hal_tables(db)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n"
            f"  1ère : {counts_1}\n  2ème : {counts_2}"
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
                {"author": {"id": "https://openalex.org/A999001", "display_name": "Hector Vidal"},
                 "author_position": "first", "institutions": [], "raw_affiliation_strings": ["UCA"]},
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
                {"author": {"id": "https://openalex.org/A999001", "display_name": "Hector Vidal"},
                 "author_position": "first", "institutions": [], "raw_affiliation_strings": []},
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
                {"author": {"id": "https://openalex.org/A999002", "display_name": "Irene Blanc"},
                 "author_position": "first", "institutions": [], "raw_affiliation_strings": []},
            ],
            "open_access": {"oa_status": "closed", "is_oa": False},
        },
    },
]


def _insert_oa_staging(cur, docs):
    for doc in docs:
        cur.execute("""
            INSERT INTO staging_openalex (openalex_id, doi, raw_data, processed)
            VALUES (%s, %s, %s, FALSE)
            ON CONFLICT (openalex_id) DO UPDATE SET processed = FALSE
        """, (doc["openalex_id"], doc["doi"], Json(doc["raw_data"])))


def _run_normalize_oa(cur):
    from processing.normalize_openalex import process_work
    cur.execute("""
        SELECT id, openalex_id, doi, raw_data
        FROM staging_openalex WHERE processed = FALSE ORDER BY id
    """)
    rows = cur.fetchall()
    processed = 0
    for row in rows:
        if process_work(cur, row):
            processed += 1
    return processed


def _count_oa_tables(cur) -> dict:
    counts = {}
    for t in ["publications", "openalex_documents", "openalex_authors", "openalex_authorships"]:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {t}")
        counts[t] = cur.fetchone()["cnt"]
    return counts


class TestNormalizeOpenalexIdempotence:
    def test_double_run_same_counts(self, db):
        _insert_oa_staging(db, OA_STAGING_DOCS)

        processed_1 = _run_normalize_oa(db)
        counts_1 = _count_oa_tables(db)
        assert processed_1 == 3

        db.execute("UPDATE staging_openalex SET processed = FALSE")
        _run_normalize_oa(db)
        counts_2 = _count_oa_tables(db)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n"
            f"  1ère : {counts_1}\n  2ème : {counts_2}"
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


def _insert_wos_staging(cur, docs):
    for doc in docs:
        cur.execute("""
            INSERT INTO staging_wos (ut, doi, raw_data, processed)
            VALUES (%s, %s, %s, FALSE)
            ON CONFLICT (ut) DO UPDATE SET processed = FALSE
        """, (doc["ut"], doc["doi"], Json(doc["raw_data"])))


def _run_normalize_wos(cur):
    plain_cur = cur.connection.cursor()
    from processing.normalize_wos import process_record
    plain_cur.execute("""
        SELECT id, ut, doi, raw_data
        FROM staging_wos WHERE processed = FALSE ORDER BY id
    """)
    rows = plain_cur.fetchall()
    processed = 0
    for row in rows:
        if process_record(plain_cur, row):
            processed += 1
    return processed


def _count_wos_tables(cur) -> dict:
    counts = {}
    for t in ["publications", "wos_documents", "wos_authors", "wos_authorships"]:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {t}")
        counts[t] = cur.fetchone()["cnt"]
    return counts


class TestNormalizeWosIdempotence:
    def test_double_run_same_counts(self, db):
        _insert_wos_staging(db, WOS_STAGING_DOCS)

        processed_1 = _run_normalize_wos(db)
        counts_1 = _count_wos_tables(db)
        assert processed_1 == 3

        db.execute("UPDATE staging_wos SET processed = FALSE")
        _run_normalize_wos(db)
        counts_2 = _count_wos_tables(db)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n"
            f"  1ère : {counts_1}\n  2ème : {counts_2}"
        )


# ══════════════════════════════════════════════════════════════════
# Inter-sources
# ══════════════════════════════════════════════════════════════════

SHARED_DOI = "10.9999/shared-article-001"

INTER_HAL_DOCS = [
    {
        "halid": "hal-99100001",
        "doi": SHARED_DOI,
        "collection": "TEST",
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
        "collection": "TEST",
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
                {"author": {"id": "https://openalex.org/A991001", "display_name": "Alice Dupont"},
                 "author_position": "first", "institutions": [], "raw_affiliation_strings": []},
                {"author": {"id": "https://openalex.org/A991002", "display_name": "Bob Martin"},
                 "author_position": "last", "institutions": [], "raw_affiliation_strings": []},
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
                {"author": {"id": "https://openalex.org/A991003", "display_name": "Charlie Noid"},
                 "author_position": "first", "institutions": [], "raw_affiliation_strings": []},
            ],
            "open_access": {"oa_status": "closed", "is_oa": False},
        },
    },
]


class TestNormalizeInterSourceIdempotence:
    """Normaliser HAL puis OA puis relancer HAL ne crée pas de doublons."""

    def test_hal_then_oa_then_hal_again(self, db):
        _insert_hal_staging(db, INTER_HAL_DOCS)
        _insert_oa_staging(db, INTER_OA_DOCS)

        # Passe 1 : HAL
        _run_normalize_hal(db)
        db.execute("SELECT COUNT(*) AS cnt FROM publications")
        pubs_after_hal = db.fetchone()["cnt"]

        # Passe 2 : OA
        _run_normalize_oa(db)
        db.execute("SELECT COUNT(*) AS cnt FROM publications")
        pubs_after_oa = db.fetchone()["cnt"]

        # L'article partagé ne doit pas être dupliqué (même DOI)
        db.execute(
            "SELECT COUNT(*) AS cnt FROM publications WHERE lower(doi) = lower(%s)",
            (SHARED_DOI,))
        assert db.fetchone()["cnt"] == 1, "L'article partagé ne doit exister qu'une fois"

        # Le rapport HAL sans DOI + l'article OA-only = 2 pubs de plus
        assert pubs_after_oa == pubs_after_hal + 1, (
            f"OA devrait ajouter 1 pub (OA-only), pas plus. "
            f"HAL={pubs_after_hal}, après OA={pubs_after_oa}"
        )

        # Passe 3 : relancer HAL
        db.execute("UPDATE staging_hal SET processed = FALSE")
        _run_normalize_hal(db)
        db.execute("SELECT COUNT(*) AS cnt FROM publications")
        pubs_after_hal2 = db.fetchone()["cnt"]

        assert pubs_after_hal2 == pubs_after_oa, (
            f"Relancer HAL ne devrait rien créer. "
            f"Avant={pubs_after_oa}, après={pubs_after_hal2}"
        )

    def test_shared_doi_same_journal(self, db):
        """L'article partagé pointe vers le même journal, pas un doublon."""
        _insert_hal_staging(db, INTER_HAL_DOCS)
        _insert_oa_staging(db, INTER_OA_DOCS)

        _run_normalize_hal(db)
        _run_normalize_oa(db)

        db.execute("""
            SELECT COUNT(*) AS cnt FROM journals
            WHERE title_normalized LIKE '%%geochemistry international%%'
        """)
        assert db.fetchone()["cnt"] == 1, "Le journal partagé ne doit exister qu'une fois"


# ══════════════════════════════════════════════════════════════════
# create_persons_from_source_authorships
# ══════════════════════════════════════════════════════════════════

def _setup_persons_test_data(db):
    """Crée une chaîne complète de données pour tester create_persons :
    publications → hal_documents → hal_authors → hal_authorships (is_uca=TRUE)
    """
    # Publications
    db.execute("""
        INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
        VALUES (90001, 'Test Pub Alpha', 'test pub alpha', 'article', 2024),
               (90002, 'Test Pub Beta', 'test pub beta', 'thesis', 2024)
    """)

    # HAL documents
    db.execute("""
        INSERT INTO hal_documents (id, halid, title, pub_year, doc_type, publication_id)
        VALUES (90001, 'hal-90000001', 'Test Pub Alpha', 2024, 'ART', 90001),
               (90002, 'hal-90000002', 'Test Pub Beta', 2024, 'THESE', 90002)
    """)

    # HAL authors (avec hal_person_id pour l'étape 0)
    db.execute("""
        INSERT INTO hal_authors (id, hal_person_id, full_name, last_name, first_name, orcid)
        VALUES (90001, 900001, 'Eve Leroy', 'Leroy', 'Eve', '0000-0001-9999-0001'),
               (90002, 900002, 'Frank Moreau', 'Moreau', 'Frank', NULL),
               (90003, NULL, 'Grace Petit', 'Petit', 'Grace', NULL)
    """)

    # HAL authorships (is_uca=TRUE, person_id=NULL)
    db.execute("""
        INSERT INTO hal_authorships
            (id, hal_document_id, hal_author_id, author_position, is_uca,
             person_id, author_name_normalized)
        VALUES
            (90001, 90001, 90001, 0, TRUE, NULL, 'eve leroy'),
            (90002, 90001, 90002, 1, TRUE, NULL, 'frank moreau'),
            (90003, 90002, 90001, 0, TRUE, NULL, 'eve leroy'),
            (90004, 90002, 90003, 1, TRUE, NULL, 'grace petit')
    """)


def _run_create_persons(db):
    """Exécute create_persons sur le curseur de test."""
    from processing.create_persons_from_source_authorships import (
        get_all_unlinked_authorships, load_linked_authorships_by_pub,
        load_name_form_map, step0_hal_accounts, step1_cross_source,
        step2_orcid, step3_name_forms,
    )

    all_authorships = get_all_unlinked_authorships(db)
    linked_ids = set()

    step0_hal_accounts(db, all_authorships, linked_ids, dry_run=False)
    linked_index = load_linked_authorships_by_pub(db)
    step1_cross_source(db, all_authorships, linked_ids, linked_index, dry_run=False)
    step2_orcid(db, all_authorships, linked_ids, dry_run=False)
    name_form_map = load_name_form_map(db)
    step3_name_forms(db, all_authorships, linked_ids, name_form_map, dry_run=False)

    return len(linked_ids)


def _count_persons_tables(db) -> dict:
    counts = {}
    for t in ["persons", "person_name_forms", "person_identifiers"]:
        db.execute(f"SELECT COUNT(*) AS cnt FROM {t}")
        counts[t] = db.fetchone()["cnt"]
    # Aussi les authorships rattachées
    db.execute("SELECT COUNT(*) AS cnt FROM hal_authorships WHERE person_id IS NOT NULL")
    counts["hal_as_linked"] = db.fetchone()["cnt"]
    return counts


class TestCreatePersonsIdempotence:
    """create_persons produit le même résultat si lancé deux fois."""

    def test_double_run_same_counts(self, db):
        _setup_persons_test_data(db)

        # Passe 1
        linked_1 = _run_create_persons(db)
        counts_1 = _count_persons_tables(db)

        assert linked_1 == 4, f"4 authorships à rattacher, got {linked_1}"
        assert counts_1["hal_as_linked"] == 4

        # Reset : remettre person_id à NULL sur les authorships
        # (mais PAS sur hal_authors — en production, hal_authors.person_id
        # persiste entre les relances via le dual-write)
        db.execute("UPDATE hal_authorships SET person_id = NULL")

        # Passe 2
        _run_create_persons(db)
        counts_2 = _count_persons_tables(db)

        assert counts_2 == counts_1, (
            f"Compteurs différents après 2e passe !\n"
            f"  1ère : {counts_1}\n  2ème : {counts_2}"
        )

    def test_same_hal_person_id_one_person(self, db):
        """Deux authorships avec le même hal_person_id → une seule personne."""
        _setup_persons_test_data(db)
        _run_create_persons(db)

        # Eve Leroy (hal_person_id=900001) apparaît sur 2 documents
        db.execute("""
            SELECT DISTINCT person_id FROM hal_authorships
            WHERE hal_author_id = 90001 AND person_id IS NOT NULL
        """)
        rows = db.fetchall()
        assert len(rows) == 1, "Eve Leroy devrait être une seule personne"

    def test_orcid_registered(self, db):
        """L'ORCID d'Eve Leroy est enregistré dans person_identifiers."""
        _setup_persons_test_data(db)
        _run_create_persons(db)

        db.execute("""
            SELECT COUNT(*) AS cnt FROM person_identifiers
            WHERE id_type = 'orcid' AND id_value = '0000-0001-9999-0001'
        """)
        assert db.fetchone()["cnt"] == 1
