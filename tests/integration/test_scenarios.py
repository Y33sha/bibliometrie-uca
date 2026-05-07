"""Tests d'intégration — nécessitent la base bibliometrie_test."""

import psycopg
import pytest

from application.persons import merge_person
from application.publications import find_or_create, refresh_from_sources
from domain.errors import ConflictError
from infrastructure.repositories import person_repository, publication_repository


@pytest.fixture
def person_repo(db):
    return person_repository(db)


@pytest.fixture
def pub_repo(db):
    return publication_repository(db)


# ── Helpers ──


def create_person(db, last_name, first_name):
    db.execute(
        """
        INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id
    """,
        (last_name, first_name, last_name, first_name),
    )
    return db.fetchone()["id"]


def create_persons_rh(db, person_id, **kwargs):
    db.execute(
        """
        INSERT INTO persons_rh (person_id, department_name)
        VALUES (%s, %s)
    """,
        (person_id, kwargs.get("department_name", "Test")),
    )


def create_journal(db, title="Test Journal"):
    db.execute(
        "INSERT INTO journals (title, title_normalized) VALUES (%s, lower(%s)) RETURNING id",
        (title, title),
    )
    return db.fetchone()["id"]


def create_publication(db, title, doi=None, pub_year=2024, journal_id=None):
    db.execute(
        """
        INSERT INTO publications (title, pub_year, doi, journal_id)
        VALUES (%s, %s, %s, %s) RETURNING id
    """,
        (title, pub_year, doi, journal_id),
    )
    return db.fetchone()["id"]


# ── DOI case-insensitive (bug corrigé 2026-03-31) ──


class TestDoiCaseInsensitive:
    """La contrainte unique sur DOI est case-insensitive (lower(doi)).
    Les lookups doivent aussi être case-insensitive."""

    def test_unique_constraint_blocks_case_variant(self, db):
        create_publication(db, "Pub A", doi="10.1103/PhysRevC.111.024905")
        with pytest.raises(psycopg.errors.UniqueViolation):
            create_publication(db, "Pub B", doi="10.1103/physrevc.111.024905")

    def test_lookup_finds_case_variant(self, db):
        create_publication(db, "Pub A", doi="10.1103/PhysRevC.111.024905")
        db.execute(
            "SELECT id FROM publications WHERE lower(doi) = lower(%s)",
            ("10.1103/physrevc.111.024905",),
        )
        assert db.fetchone() is not None


# ── Service publications ──


class TestPublicationService:
    def test_create_new(self, db, pub_repo):
        pub_id, is_new = find_or_create(
            db,
            title="Test Article",
            title_normalized="test article",
            pub_year=2024,
            doc_type="article",
            doi="10.1234/test",
            repo=pub_repo,
        )
        assert pub_id is not None
        assert is_new is True

    def test_find_by_doi_case_insensitive(self, db, pub_repo):
        pub_id1, _ = find_or_create(
            db,
            title="Pub A",
            title_normalized="pub a",
            pub_year=2024,
            doi="10.1103/PhysRevC.111.024905",
            repo=pub_repo,
        )
        pub_id2, is_new = find_or_create(
            db,
            title="Pub A variant",
            title_normalized="pub a variant",
            pub_year=2024,
            doi="10.1103/physrevc.111.024905",
            repo=pub_repo,
        )
        assert pub_id2 == pub_id1
        assert is_new is False

    def test_same_title_year_journal_no_merge_without_doi(self, db, pub_repo):
        """Sans DOI commun, meme titre+annee+journal -> pas de fusion."""
        journal_id = create_journal(db, "Nature")
        pub_id1, _ = find_or_create(
            db,
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            journal_id=journal_id,
            repo=pub_repo,
        )
        pub_id2, is_new = find_or_create(
            db,
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            journal_id=journal_id,
            repo=pub_repo,
        )
        assert pub_id2 != pub_id1
        assert is_new is True

    def test_no_title_match_without_journal(self, db, pub_repo):
        """Sans journal_id, pas de dédup par titre — deux publications créées."""
        pub_id1, _ = find_or_create(
            db,
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            repo=pub_repo,
        )
        pub_id2, is_new = find_or_create(
            db,
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            repo=pub_repo,
        )
        assert pub_id2 != pub_id1
        assert is_new is True

    def test_enrich_via_refresh(self, db, pub_repo):
        """refresh_from_sources enrichit les métadonnées depuis les source_publications."""
        journal_id = create_journal(db, "Science")
        pub_id, _ = find_or_create(
            db,
            title="Pub",
            title_normalized="pub",
            pub_year=2024,
            doi="10.5555/enrich-test",
            oa_status="unknown",
            repo=pub_repo,
        )
        # Créer un source_document avec plus d'info
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, pub_year,
                                          publication_id, oa_status, journal_id)
            VALUES ('openalex', 'W999enrich', 'Pub', 2024, %s, 'gold', %s)
        """,
            (pub_id, journal_id),
        )
        refresh_from_sources(db, pub_id, repo=pub_repo)
        db.execute("SELECT oa_status, journal_id FROM publications WHERE id = %s", (pub_id,))
        row = db.fetchone()
        assert row["journal_id"] == journal_id
        assert row["oa_status"] == "gold"

    def test_refresh_auto_merges_when_doi_already_taken(self, db, pub_repo):
        """Régression : la promotion d'un DOI déjà occupé par une autre
        publication doit déclencher une fusion automatique au lieu de
        violer publications_doi_lower_key.

        Cas réel : thèse 2020CLFAC037 dont le DOI ABES (10.70675/...)
        a été créé par OpenAlex (sans NNT) sur une pub A, puis promu
        depuis la source_publication theses.fr d'une pub B (créée par
        NNT sans DOI). Avant fix : crash IntegrityError.
        """
        existing, _ = find_or_create(
            db,
            title="Thèse côté OpenAlex",
            title_normalized="these cote openalex",
            pub_year=2020,
            doc_type="thesis",
            doi="10.70675/regression-test",
            repo=pub_repo,
        )
        current, _ = find_or_create(
            db,
            title="Thèse côté theses.fr",
            title_normalized="these cote theses fr",
            pub_year=2020,
            doc_type="thesis",
            repo=pub_repo,
        )
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, pub_year,
                                          publication_id, doi)
            VALUES ('theses', '2020REGRESS', 'Thèse', 2020, %s, %s)
            """,
            (current, "10.70675/regression-test"),
        )

        refresh_from_sources(db, current, repo=pub_repo)

        # current est vivant et a hérité du DOI
        db.execute("SELECT doi FROM publications WHERE id = %s", (current,))
        row = db.fetchone()
        assert row is not None
        assert row["doi"] == "10.70675/regression-test"
        # existing a été absorbée
        db.execute("SELECT id FROM publications WHERE id = %s", (existing,))
        assert db.fetchone() is None

    def test_allow_create_false(self, db, pub_repo):
        pub_id, is_new = find_or_create(
            db,
            title="Ghost",
            title_normalized="ghost",
            pub_year=2024,
            allow_create=False,
            repo=pub_repo,
        )
        assert pub_id is None
        assert is_new is False


# ── Cohérence enum sources ──


class TestSourcesEnum:
    def test_python_matches_db(self, db):
        """utils.sources.ALL_SOURCES doit correspondre à l'enum source_type en base."""
        from domain.sources import ALL_SOURCES_SET

        db.execute("SELECT unnest(enum_range(NULL::source_type))::text")
        db_sources = {row["unnest"] for row in db.fetchall()}
        assert ALL_SOURCES_SET == db_sources, (
            f"Désynchronisation Python/DB !\n"
            f"  Python : {sorted(ALL_SOURCES_SET)}\n"
            f"  DB     : {sorted(db_sources)}"
        )


# ── Merge persons ──


class TestMergePersons:
    def test_merge_transfers_name_forms(self, db, person_repo):
        target = create_person(db, "Dupont", "Jean")
        source = create_person(db, "Dupont", "J.")

        db.execute(
            """
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES ('jean dupont', %s)
        """,
            ([target],),
        )
        db.execute(
            """
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES ('j dupont', %s)
        """,
            ([source],),
        )

        merge_person(db, target, source, repo=person_repo)

        # Source supprimée
        db.execute("SELECT 1 FROM persons WHERE id = %s", (source,))
        assert db.fetchone() is None

        # Name forms transférées
        db.execute("SELECT person_ids FROM person_name_forms WHERE name_form = 'j dupont'")
        row = db.fetchone()
        assert target in row["person_ids"]
        assert source not in row["person_ids"]

    def test_merge_blocked_if_both_rh(self, db, person_repo):
        target = create_person(db, "Dupont", "Jean")
        source = create_person(db, "Dupont", "J.")
        create_persons_rh(db, target, matricule="MAT-001")
        create_persons_rh(db, source, matricule="MAT-002")

        with pytest.raises(ConflictError, match="REFUS de fusion"):
            merge_person(db, target, source, repo=person_repo)

        # Les deux personnes existent toujours
        db.execute("SELECT 1 FROM persons WHERE id = %s", (source,))
        assert db.fetchone() is not None

    def test_merge_allowed_if_only_target_has_rh(self, db, person_repo):
        target = create_person(db, "Dupont", "Jean")
        source = create_person(db, "Dupont", "J.")
        create_persons_rh(db, target, matricule="MAT-001")

        merge_person(db, target, source, repo=person_repo)

        db.execute("SELECT 1 FROM persons WHERE id = %s", (source,))
        assert db.fetchone() is None
