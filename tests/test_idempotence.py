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
