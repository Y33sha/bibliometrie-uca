"""Tests d'intégration — nécessitent la base publisher_stats_test."""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest
from services.persons import merge_person
from services.publications import find_or_create, find_by_doi


# ── Helpers ──

def create_person(db, last_name, first_name):
    db.execute("""
        INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id
    """, (last_name, first_name, last_name, first_name))
    return db.fetchone()["id"]


def create_persons_rh(db, person_id, **kwargs):
    db.execute("""
        INSERT INTO persons_rh (person_id, department_name)
        VALUES (%s, %s)
    """, (person_id, kwargs.get("department_name", "Test")))


def create_journal(db, title="Test Journal"):
    db.execute("INSERT INTO journals (title, title_normalized) VALUES (%s, lower(%s)) RETURNING id",
               (title, title))
    return db.fetchone()["id"]


def create_publication(db, title, doi=None, pub_year=2024, journal_id=None):
    db.execute("""
        INSERT INTO publications (title, pub_year, doi, journal_id)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (title, pub_year, doi, journal_id))
    return db.fetchone()["id"]


# ── DOI case-insensitive (bug corrigé 2026-03-31) ──

class TestDoiCaseInsensitive:
    """La contrainte unique sur DOI est case-insensitive (lower(doi)).
    Les lookups doivent aussi être case-insensitive."""

    def test_unique_constraint_blocks_case_variant(self, db):
        create_publication(db, "Pub A", doi="10.1103/PhysRevC.111.024905")
        with pytest.raises(Exception):  # UniqueViolation
            create_publication(db, "Pub B", doi="10.1103/physrevc.111.024905")

    def test_lookup_finds_case_variant(self, db):
        create_publication(db, "Pub A", doi="10.1103/PhysRevC.111.024905")
        db.execute("SELECT id FROM publications WHERE lower(doi) = lower(%s)",
                   ("10.1103/physrevc.111.024905",))
        assert db.fetchone() is not None


# ── Service publications ──

class TestPublicationService:
    def test_create_new(self, db):
        pub_id, is_new = find_or_create(
            db, title="Test Article", title_normalized="test article",
            pub_year=2024, doc_type="article", doi="10.1234/test")
        assert pub_id is not None
        assert is_new is True

    def test_find_by_doi_case_insensitive(self, db):
        pub_id1, _ = find_or_create(
            db, title="Pub A", title_normalized="pub a",
            pub_year=2024, doi="10.1103/PhysRevC.111.024905")
        pub_id2, is_new = find_or_create(
            db, title="Pub A variant", title_normalized="pub a variant",
            pub_year=2024, doi="10.1103/physrevc.111.024905")
        assert pub_id2 == pub_id1
        assert is_new is False

    def test_find_by_title_year_journal(self, db):
        journal_id = create_journal(db, "Nature")
        pub_id1, _ = find_or_create(
            db, title="My Article", title_normalized="my article",
            pub_year=2024, doc_type="article", journal_id=journal_id)
        pub_id2, is_new = find_or_create(
            db, title="My Article", title_normalized="my article",
            pub_year=2024, doc_type="article", journal_id=journal_id)
        assert pub_id2 == pub_id1
        assert is_new is False

    def test_no_title_match_without_journal(self, db):
        """Sans journal_id, pas de dédup par titre — deux publications créées."""
        pub_id1, _ = find_or_create(
            db, title="My Article", title_normalized="my article",
            pub_year=2024, doc_type="article")
        pub_id2, is_new = find_or_create(
            db, title="My Article", title_normalized="my article",
            pub_year=2024, doc_type="article")
        assert pub_id2 != pub_id1
        assert is_new is True

    def test_enrich_on_doi_match(self, db):
        """Quand on retrouve par DOI, les métadonnées manquantes sont enrichies."""
        journal_id = create_journal(db, "Science")
        pub_id, _ = find_or_create(
            db, title="Pub", title_normalized="pub",
            pub_year=2024, doi="10.5555/enrich-test",
            oa_status="unknown")
        # Deuxième appel avec plus d'info
        pub_id2, is_new = find_or_create(
            db, title="Pub", title_normalized="pub",
            pub_year=2024, doi="10.5555/enrich-test",
            oa_status="gold", journal_id=journal_id)
        assert pub_id2 == pub_id
        assert is_new is False
        db.execute("SELECT oa_status, journal_id FROM publications WHERE id = %s", (pub_id,))
        row = db.fetchone()
        assert row["journal_id"] == journal_id
        assert row["oa_status"] == "gold"

    def test_allow_create_false(self, db):
        pub_id, is_new = find_or_create(
            db, title="Ghost", title_normalized="ghost",
            pub_year=2024, allow_create=False)
        assert pub_id is None
        assert is_new is False


# ── Merge persons ──

class TestMergePersons:
    def test_merge_transfers_name_forms(self, db):
        target = create_person(db, "Dupont", "Jean")
        source = create_person(db, "Dupont", "J.")

        db.execute("""
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES ('jean dupont', %s)
        """, ([target],))
        db.execute("""
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES ('j dupont', %s)
        """, ([source],))

        merge_person(db, target, source)

        # Source supprimée
        db.execute("SELECT 1 FROM persons WHERE id = %s", (source,))
        assert db.fetchone() is None

        # Name forms transférées
        db.execute("SELECT person_ids FROM person_name_forms WHERE name_form = 'j dupont'")
        row = db.fetchone()
        assert target in row["person_ids"]
        assert source not in row["person_ids"]

    def test_merge_blocked_if_both_rh(self, db):
        target = create_person(db, "Dupont", "Jean")
        source = create_person(db, "Dupont", "J.")
        create_persons_rh(db, target, matricule="MAT-001")
        create_persons_rh(db, source, matricule="MAT-002")

        with pytest.raises(RuntimeError, match="REFUS de fusion"):
            merge_person(db, target, source)

        # Les deux personnes existent toujours
        db.execute("SELECT 1 FROM persons WHERE id = %s", (source,))
        assert db.fetchone() is not None

    def test_merge_allowed_if_only_target_has_rh(self, db):
        target = create_person(db, "Dupont", "Jean")
        source = create_person(db, "Dupont", "J.")
        create_persons_rh(db, target, matricule="MAT-001")

        merge_person(db, target, source)

        db.execute("SELECT 1 FROM persons WHERE id = %s", (source,))
        assert db.fetchone() is None
