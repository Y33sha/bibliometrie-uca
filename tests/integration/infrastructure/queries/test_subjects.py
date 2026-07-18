"""Tests d'intégration pour `infrastructure.queries.subjects`."""

from sqlalchemy import text

from infrastructure.queries.subjects import (
    PgSubjectsAdminQueries,
    clear_publication_subjects,
    link_publication_subject,
    upsert_subject,
)


def _create_pub(conn, title="X"):
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, doc_type) "
            "VALUES (:t, 2024, 'article') RETURNING id"
        ),
        {"t": title},
    ).scalar_one()


class TestUpsertSubject:
    def test_creates_new(self, sa_sync_conn):
        sid = upsert_subject(sa_sync_conn, label="machine learning")
        assert sid > 0
        row = sa_sync_conn.execute(
            text("SELECT label, language FROM subjects WHERE id = :id"), {"id": sid}
        ).one()
        assert row.label == "machine learning"
        assert row.language is None

    def test_stores_language(self, sa_sync_conn):
        sid = upsert_subject(sa_sync_conn, label="Machine Learning", language="en")
        language = sa_sync_conn.execute(
            text("SELECT language FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        assert language == "en"

    def test_dedup_case_insensitive(self, sa_sync_conn):
        a = upsert_subject(sa_sync_conn, label="Machine Learning")
        b = upsert_subject(sa_sync_conn, label="machine learning")
        assert a == b
        # La casse originale est conservée.
        label = sa_sync_conn.execute(
            text("SELECT label FROM subjects WHERE id = :id"), {"id": a}
        ).scalar_one()
        assert label == "Machine Learning"

    def test_normalizes_whitespace(self, sa_sync_conn):
        a = upsert_subject(sa_sync_conn, label="  machine    learning  ")
        b = upsert_subject(sa_sync_conn, label="machine learning")
        assert a == b

    def test_language_first_non_null_wins(self, sa_sync_conn):
        sid = upsert_subject(sa_sync_conn, label="Biology", language="en")
        upsert_subject(sa_sync_conn, label="biology", language="fr")
        language = sa_sync_conn.execute(
            text("SELECT language FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        assert language == "en"


class TestLinkAndClear:
    def test_link_creates_row(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(sa_sync_conn, publication_id=pub, subject_id=sid, source="hal")
        source = sa_sync_conn.execute(
            text(
                "SELECT source FROM publication_subjects "
                "WHERE publication_id = :p AND subject_id = :s"
            ),
            {"p": pub, "s": sid},
        ).scalar_one()
        assert source == "hal"

    def test_link_same_subject_two_sources(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(sa_sync_conn, publication_id=pub, subject_id=sid, source="hal")
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex"
        )
        n = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM publication_subjects WHERE publication_id = :p"),
            {"p": pub},
        ).scalar_one()
        assert n == 2

    def test_link_idempotent_same_source(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex"
        )
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex"
        )
        n = sa_sync_conn.execute(
            text(
                "SELECT count(*) AS n FROM publication_subjects "
                "WHERE publication_id = :p AND source = 'openalex'"
            ),
            {"p": pub},
        ).scalar_one()
        assert n == 1

    def test_clear_only_removes_target_source(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(sa_sync_conn, publication_id=pub, subject_id=sid, source="hal")
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex"
        )
        n = clear_publication_subjects(sa_sync_conn, publication_id=pub, source="hal")
        assert n == 1
        sources = (
            sa_sync_conn.execute(
                text("SELECT source FROM publication_subjects WHERE publication_id = :p"),
                {"p": pub},
            )
            .scalars()
            .all()
        )
        assert sources == ["openalex"]

    def test_subject_survives_publication_delete(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="orphan candidate")
        link_publication_subject(sa_sync_conn, publication_id=pub, subject_id=sid, source="hal")
        sa_sync_conn.execute(text("DELETE FROM publications WHERE id = :p"), {"p": pub})
        n_links = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM publication_subjects WHERE subject_id = :s"),
            {"s": sid},
        ).scalar_one()
        assert n_links == 0
        n_subj = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM subjects WHERE id = :s"), {"s": sid}
        ).scalar_one()
        assert n_subj == 1


class TestListSubjectsSearch:
    """Recherche `list_subjects` accent-insensible (régression : `lower(label) LIKE`
    était sensible aux accents)."""

    def test_search_ignores_accents(self, sa_sync_conn):
        upsert_subject(sa_sync_conn, label="épidémiologie quantique")
        queries = PgSubjectsAdminQueries(sa_sync_conn)

        # Requête sans accent → trouve le label accentué.
        found = queries.list_subjects(
            q="epidemiologie quantique", limit=10, offset=0, min_usage_count=0
        )
        assert any(s.label == "épidémiologie quantique" for s in found)

        # Requête accentuée → trouve aussi (symétrie via unaccent des deux côtés).
        found_accented = queries.list_subjects(
            q="épidémiologie quantique", limit=10, offset=0, min_usage_count=0
        )
        assert any(s.label == "épidémiologie quantique" for s in found_accented)
