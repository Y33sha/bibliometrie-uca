"""Tests d'intégration pour `infrastructure.db.queries.hal_problems`."""

from infrastructure.db.queries.hal_problems import (
    hal_affiliation_conflicts,
    hal_duplicate_pubs_by_doi,
    hal_duplicate_pubs_by_metadata,
    hal_missing_collections,
    hal_missing_collections_labs,
)


def _create_pub(db, title="T", doi=None, pub_year=2024, title_normalized=None):
    db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
        VALUES (%s, %s, %s, 'article', %s) RETURNING id
        """,
        (title, title_normalized or title.lower(), pub_year, doi),
    )
    return db.fetchone()["id"]


def _create_hal_sd(db, pub_id, source_id, doi=None, hal_collections=None, pub_year=2024, title="T"):
    db.execute(
        """
        INSERT INTO source_publications
            (source, source_id, title, publication_id, doi, hal_collections, pub_year)
        VALUES ('hal', %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (source_id, title, pub_id, doi, hal_collections, pub_year),
    )
    return db.fetchone()["id"]


def _create_lab(db, code="LAB", hal_collection=None):
    db.execute(
        """
        INSERT INTO structures (code, name, structure_type, hal_collection)
        VALUES (%s, 'L', 'labo', %s) RETURNING id
        """,
        (code, hal_collection),
    )
    return db.fetchone()["id"]


class TestHalDuplicatePubsByDoi:
    def test_detects_two_hal_deposits_same_doi(self, db):
        pub = _create_pub(db)
        _create_hal_sd(db, pub, "h-1", doi="10.1/shared")
        _create_hal_sd(db, pub, "h-2", doi="10.1/shared")

        res = hal_duplicate_pubs_by_doi(db, page=1, per_page=50)
        assert res["total"] >= 1
        assert any(len(p["halids"]) >= 2 for p in res["pairs"])

    def test_noop_without_duplicates(self, db):
        pub = _create_pub(db)
        _create_hal_sd(db, pub, "h-uniq", doi="10.1/u")
        res = hal_duplicate_pubs_by_doi(db, page=1, per_page=50)
        assert res["total"] == 0


class TestHalDuplicatePubsByMetadata:
    def test_detects_pair_with_same_title_and_year(self, db):
        # Titre > 30 chars + même année + même doc_type + taille auteurs ±2
        title = "Article Title That Is Long Enough To Trigger Metadata Detection"
        title_norm = title.lower()
        p1 = _create_pub(db, title=title, title_normalized=title_norm)
        p2 = _create_pub(db, title=title, title_normalized=title_norm)
        _create_hal_sd(db, p1, "h-meta-1")
        _create_hal_sd(db, p2, "h-meta-2")

        res = hal_duplicate_pubs_by_metadata(db, page=1, per_page=50)
        assert res["total"] >= 1


class TestHalMissingCollectionsLabs:
    def test_lists_labs_with_hal_collection(self, db):
        lab = _create_lab(db, code="LAB-1", hal_collection="COLL-X")
        _create_lab(db, code="LAB-NO", hal_collection=None)

        labs = hal_missing_collections_labs(db)
        ids = [lab_["id"] for lab_ in labs]
        assert lab in ids
        assert all(lab_["hal_collection"] for lab_ in labs)


class TestHalMissingCollections:
    def test_returns_error_for_lab_without_collection(self, db):
        lab = _create_lab(db, code="LAB-NO-COL", hal_collection=None)
        res = hal_missing_collections(db, lab_id=lab, page=1, per_page=50)
        assert res == {"error": "no_collection"}

    def test_returns_empty_when_no_missing(self, db):
        lab = _create_lab(db, code="LAB-X", hal_collection="COLL-X")
        res = hal_missing_collections(db, lab_id=lab, page=1, per_page=50)
        assert res["total"] == 0
        assert res["lab_acronym"] is None  # structure sans acronyme


class TestHalAffiliationConflicts:
    def test_noop_when_no_data(self, db):
        res = hal_affiliation_conflicts(db, page=1, per_page=50)
        assert res["total"] == 0
        assert res["publications"] == []
