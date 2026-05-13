"""Tests d'intégration — nécessitent la base bibliometrie_test."""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from application.persons import merge_person
from application.publications import find_or_create, refresh_from_sources
from domain.errors import ConflictError
from infrastructure.repositories import person_repository, publication_repository


@pytest.fixture
def person_repo(sa_sync_conn):
    return person_repository(sa_sync_conn)


@pytest.fixture
def pub_repo(sa_sync_conn):
    return publication_repository(sa_sync_conn)


# ── Helpers ──


def create_person(conn, last_name, first_name):
    return conn.execute(
        text(
            """
            INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
            VALUES (:last, :first, lower(:last), lower(:first)) RETURNING id
            """
        ),
        {"last": last_name, "first": first_name},
    ).scalar_one()


def create_persons_rh(conn, person_id, **kwargs):
    conn.execute(
        text("INSERT INTO persons_rh (person_id, department_name) VALUES (:pid, :dept)"),
        {"pid": person_id, "dept": kwargs.get("department_name", "Test")},
    )


def create_journal(conn, title="Test Journal"):
    return conn.execute(
        text("INSERT INTO journals (title, title_normalized) VALUES (:t, lower(:t)) RETURNING id"),
        {"t": title},
    ).scalar_one()


def create_publication(conn, title, doi=None, pub_year=2024, journal_id=None):
    return conn.execute(
        text(
            """
            INSERT INTO publications (title, pub_year, doi, journal_id)
            VALUES (:title, :py, :doi, :jid) RETURNING id
            """
        ),
        {"title": title, "py": pub_year, "doi": doi, "jid": journal_id},
    ).scalar_one()


# ── DOI case-insensitive (bug corrigé 2026-03-31) ──


class TestDoiCaseInsensitive:
    """La contrainte unique sur DOI est case-insensitive (lower(doi)).
    Les lookups doivent aussi être case-insensitive."""

    def test_unique_constraint_blocks_case_variant(self, sa_sync_conn):
        create_publication(sa_sync_conn, "Pub A", doi="10.1103/PhysRevC.111.024905")
        with pytest.raises(IntegrityError):
            create_publication(sa_sync_conn, "Pub B", doi="10.1103/physrevc.111.024905")

    def test_lookup_finds_case_variant(self, sa_sync_conn):
        create_publication(sa_sync_conn, "Pub A", doi="10.1103/PhysRevC.111.024905")
        result = sa_sync_conn.execute(
            text("SELECT id FROM publications WHERE lower(doi) = lower(:doi)"),
            {"doi": "10.1103/physrevc.111.024905"},
        ).first()
        assert result is not None


# ── Service publications ──


class TestPublicationService:
    def test_create_new(self, sa_sync_conn, pub_repo):
        pub_id, is_new = find_or_create(
            title="Test Article",
            title_normalized="test article",
            pub_year=2024,
            doc_type="article",
            doi="10.1234/test",
            repo=pub_repo,
        )
        assert pub_id is not None
        assert is_new is True

    def test_find_by_doi_case_insensitive(self, sa_sync_conn, pub_repo):
        pub_id1, _ = find_or_create(
            title="Pub A",
            title_normalized="pub a",
            pub_year=2024,
            doi="10.1103/PhysRevC.111.024905",
            repo=pub_repo,
        )
        pub_id2, is_new = find_or_create(
            title="Pub A variant",
            title_normalized="pub a variant",
            pub_year=2024,
            doi="10.1103/physrevc.111.024905",
            repo=pub_repo,
        )
        assert pub_id2 == pub_id1
        assert is_new is False

    def test_same_title_year_journal_no_merge_without_doi(self, sa_sync_conn, pub_repo):
        """Sans DOI commun, meme titre+annee+journal -> pas de fusion."""
        journal_id = create_journal(sa_sync_conn, "Nature")
        pub_id1, _ = find_or_create(
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            journal_id=journal_id,
            repo=pub_repo,
        )
        pub_id2, is_new = find_or_create(
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            journal_id=journal_id,
            repo=pub_repo,
        )
        assert pub_id2 != pub_id1
        assert is_new is True

    def test_no_title_match_without_journal(self, sa_sync_conn, pub_repo):
        """Sans journal_id, pas de dédup par titre — deux publications créées."""
        pub_id1, _ = find_or_create(
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            repo=pub_repo,
        )
        pub_id2, is_new = find_or_create(
            title="My Article",
            title_normalized="my article",
            pub_year=2024,
            doc_type="article",
            repo=pub_repo,
        )
        assert pub_id2 != pub_id1
        assert is_new is True

    def test_enrich_via_refresh(self, sa_sync_conn, pub_repo):
        """refresh_from_sources enrichit les métadonnées depuis les source_publications."""
        journal_id = create_journal(sa_sync_conn, "Science")
        pub_id, _ = find_or_create(
            title="Pub",
            title_normalized="pub",
            pub_year=2024,
            doi="10.5555/enrich-test",
            oa_status="unknown",
            repo=pub_repo,
        )
        # Créer un source_document avec plus d'info
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year,
                                              publication_id, oa_status, journal_id)
                VALUES ('openalex', 'W999enrich', 'Pub', 2024, :pid, 'gold', :jid)
                """
            ),
            {"pid": pub_id, "jid": journal_id},
        )
        refresh_from_sources(pub_id, repo=pub_repo)
        row = sa_sync_conn.execute(
            text("SELECT oa_status, journal_id FROM publications WHERE id = :id"),
            {"id": pub_id},
        ).one()
        assert row.journal_id == journal_id
        assert row.oa_status == "gold"

    def test_refresh_auto_merges_when_doi_already_taken(self, sa_sync_conn, pub_repo):
        """Régression : la promotion d'un DOI déjà occupé par une autre
        publication doit déclencher une fusion automatique au lieu de
        violer publications_doi_lower_key.

        Cas réel : thèse 2020CLFAC037 dont le DOI ABES (10.70675/...)
        a été créé par OpenAlex (sans NNT) sur une pub A, puis promu
        depuis la source_publication theses.fr d'une pub B (créée par
        NNT sans DOI). Avant fix : crash IntegrityError.
        """
        existing, _ = find_or_create(
            title="Thèse côté OpenAlex",
            title_normalized="these cote openalex",
            pub_year=2020,
            doc_type="thesis",
            doi="10.70675/regression-test",
            repo=pub_repo,
        )
        current, _ = find_or_create(
            title="Thèse côté theses.fr",
            title_normalized="these cote theses fr",
            pub_year=2020,
            doc_type="thesis",
            repo=pub_repo,
        )
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year,
                                              publication_id, doi)
                VALUES ('theses', '2020REGRESS', 'Thèse', 2020, :pid, :doi)
                """
            ),
            {"pid": current, "doi": "10.70675/regression-test"},
        )

        refresh_from_sources(current, repo=pub_repo)

        # current est vivant et a hérité du DOI
        doi = sa_sync_conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": current}
        ).scalar_one_or_none()
        assert doi == "10.70675/regression-test"
        # existing a été absorbée
        assert (
            sa_sync_conn.execute(
                text("SELECT id FROM publications WHERE id = :id"), {"id": existing}
            ).first()
            is None
        )

    def test_allow_create_false(self, sa_sync_conn, pub_repo):
        pub_id, is_new = find_or_create(
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
    def test_python_matches_db(self, sa_sync_conn):
        """utils.sources.ALL_SOURCES doit correspondre à l'enum source_type en base."""
        from domain.sources import ALL_SOURCES_SET

        db_sources = set(
            sa_sync_conn.execute(
                text("SELECT unnest(enum_range(NULL::source_type))::text")
            ).scalars()
        )
        assert ALL_SOURCES_SET == db_sources, (
            f"Désynchronisation Python/DB !\n"
            f"  Python : {sorted(ALL_SOURCES_SET)}\n"
            f"  DB     : {sorted(db_sources)}"
        )


# ── Merge persons ──


class TestMergePersons:
    def test_merge_transfers_name_forms(self, sa_sync_conn, person_repo):
        target = create_person(sa_sync_conn, "Dupont", "Jean")
        source = create_person(sa_sync_conn, "Dupont", "J.")

        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, persons) "
                "VALUES ('jean dupont', CAST(:p AS jsonb))"
            ),
            {"p": json.dumps({str(target): ["persons"]})},
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, persons) "
                "VALUES ('j dupont', CAST(:p AS jsonb))"
            ),
            {"p": json.dumps({str(source): ["hal"]})},
        )

        merge_person(target, source, repo=person_repo)

        # Source supprimée
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is None
        )

        # Name forms transférées : la source 'hal' attachée à `source` est
        # remontée sous la clé `target` après merge.
        persons = sa_sync_conn.execute(
            text("SELECT persons FROM person_name_forms WHERE name_form = 'j dupont'")
        ).scalar_one()
        assert str(target) in persons
        assert "hal" in persons[str(target)]
        assert str(source) not in persons

    def test_merge_blocked_if_both_rh(self, sa_sync_conn, person_repo):
        target = create_person(sa_sync_conn, "Dupont", "Jean")
        source = create_person(sa_sync_conn, "Dupont", "J.")
        create_persons_rh(sa_sync_conn, target, matricule="MAT-001")
        create_persons_rh(sa_sync_conn, source, matricule="MAT-002")

        with pytest.raises(ConflictError, match="REFUS de fusion"):
            merge_person(target, source, repo=person_repo)

        # Les deux personnes existent toujours
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is not None
        )

    def test_merge_allowed_if_only_target_has_rh(self, sa_sync_conn, person_repo):
        target = create_person(sa_sync_conn, "Dupont", "Jean")
        source = create_person(sa_sync_conn, "Dupont", "J.")
        create_persons_rh(sa_sync_conn, target, matricule="MAT-001")

        merge_person(target, source, repo=person_repo)

        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM persons WHERE id = :id"), {"id": source}
            ).first()
            is None
        )
