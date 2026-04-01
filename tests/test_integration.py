"""Tests d'intégration — nécessitent la base publisher_stats_test."""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import pytest
from utils.merge_persons import merge_person


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
    db.execute("INSERT INTO journals (title) VALUES (%s) RETURNING id", (title,))
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


# ── Merge persons ──

class TestMergePersons:
    def test_merge_transfers_name_forms(self, db):
        target = create_person(db, "Dupont", "Jean")
        source = create_person(db, "Dupont", "J.")

        db.execute("""
            INSERT INTO person_name_forms (name_form, name_form_normalized, person_ids)
            VALUES ('jean dupont', 'jean dupont', %s)
        """, ([target],))
        db.execute("""
            INSERT INTO person_name_forms (name_form, name_form_normalized, person_ids)
            VALUES ('j dupont', 'j dupont', %s)
        """, ([source],))

        merge_person(db, target, source)

        # Source supprimée
        db.execute("SELECT 1 FROM persons WHERE id = %s", (source,))
        assert db.fetchone() is None

        # Name forms transférées
        db.execute("SELECT person_ids FROM person_name_forms WHERE name_form_normalized = 'j dupont'")
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
