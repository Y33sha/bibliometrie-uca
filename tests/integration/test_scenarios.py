"""Tests d'intégration — nécessitent la base bibliometrie_test."""

import pytest
from sqlalchemy import text

from application.persons import merge_person
from application.publications import refresh_from_sources
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


# ── Service publications ──


def _seed_pub(
    repo,
    title: str,
    *,
    pub_year: int = 2024,
    doi: str | None = None,
    doc_type: str = "article",
    journal_id: int | None = None,
    oa_status: str = "unknown",
) -> int:
    """Sème une publication directement via le repo (sans cascade de matching)."""
    return repo.create(
        title=title,
        title_normalized=title.lower(),
        doc_type=doc_type,
        pub_year=pub_year,
        doi=doi,
        oa_status=oa_status,
        journal_id=journal_id,
        container_title=None,
        language=None,
    )


class TestRefreshFromSources:
    def test_enrich_via_refresh(self, sa_sync_conn, pub_repo):
        """refresh_from_sources enrichit les métadonnées depuis les source_publications."""
        journal_id = create_journal(sa_sync_conn, "Science")
        pub_id = _seed_pub(pub_repo, "Pub", doi="10.5555/enrich-test")
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


# ── Cohérence enum sources ──


class TestSourcesEnum:
    def test_python_matches_db(self, sa_sync_conn):
        """utils.sources.ALL_SOURCES doit correspondre à l'enum source_type en base."""
        from domain.sources.registry import ALL_SOURCES_SET

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


class TestPublisherTypesEnum:
    def test_python_matches_db(self, sa_sync_conn):
        """`PUBLISHER_TYPES_SET` doit correspondre à l'enum SQL `publisher_type`."""
        from domain.publishers.publisher import PUBLISHER_TYPES_SET

        db_types = set(
            sa_sync_conn.execute(
                text("SELECT unnest(enum_range(NULL::publisher_type))::text")
            ).scalars()
        )
        assert PUBLISHER_TYPES_SET == db_types, (
            f"Désynchronisation Python/DB !\n"
            f"  Python : {sorted(PUBLISHER_TYPES_SET)}\n"
            f"  DB     : {sorted(db_types)}"
        )


class TestJournalTypesEnum:
    def test_python_matches_db(self, sa_sync_conn):
        """`JOURNAL_TYPES_SET` doit correspondre à l'enum SQL `journal_type`."""
        from domain.journals.journal import JOURNAL_TYPES_SET

        db_types = set(
            sa_sync_conn.execute(
                text("SELECT unnest(enum_range(NULL::journal_type))::text")
            ).scalars()
        )
        assert JOURNAL_TYPES_SET == db_types, (
            f"Désynchronisation Python/DB !\n"
            f"  Python : {sorted(JOURNAL_TYPES_SET)}\n"
            f"  DB     : {sorted(db_types)}"
        )


# ── Merge persons ──


class TestMergePersons:
    def test_merge_transfers_name_forms(self, sa_sync_conn, person_repo):
        target = create_person(sa_sync_conn, "Dupont", "Jean")
        source = create_person(sa_sync_conn, "Dupont", "J.")

        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources) "
                "VALUES ('jean dupont', :pid, ARRAY['persons'])"
            ),
            {"pid": target},
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources) "
                "VALUES ('j dupont', :pid, ARRAY['hal'])"
            ),
            {"pid": source},
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
        # remontée sur la row `(j dupont, target)` après merge ; plus aucune
        # row ne référence l'id `source`.
        row = sa_sync_conn.execute(
            text(
                "SELECT sources FROM person_name_forms "
                "WHERE name_form = 'j dupont' AND person_id = :pid"
            ),
            {"pid": target},
        ).one()
        assert "hal" in row.sources
        assert (
            sa_sync_conn.execute(
                text("SELECT 1 FROM person_name_forms WHERE person_id = :pid"),
                {"pid": source},
            ).first()
            is None
        )

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
