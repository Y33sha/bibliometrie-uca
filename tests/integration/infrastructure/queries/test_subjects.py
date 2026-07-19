"""Tests d'intégration pour `infrastructure.queries.pipeline.subjects`."""

from sqlalchemy import text

from application.ports.pipeline.subjects import PublicationSubjectLink
from infrastructure.queries.pipeline.subjects import (
    clear_publication_subjects_for_pubs,
    link_publication_subjects_bulk,
    upsert_subject,
)


def _link(conn, publication_id, subject_id, source):
    return link_publication_subjects_bulk(
        conn, source=source, rows=[PublicationSubjectLink(publication_id, subject_id)]
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
        _link(sa_sync_conn, pub, sid, "hal")
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
        _link(sa_sync_conn, pub, sid, "hal")
        _link(sa_sync_conn, pub, sid, "openalex")
        n = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM publication_subjects WHERE publication_id = :p"),
            {"p": pub},
        ).scalar_one()
        assert n == 2

    def test_link_idempotent_same_source(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        _link(sa_sync_conn, pub, sid, "openalex")
        _link(sa_sync_conn, pub, sid, "openalex")
        n = sa_sync_conn.execute(
            text(
                "SELECT count(*) AS n FROM publication_subjects "
                "WHERE publication_id = :p AND source = 'openalex'"
            ),
            {"p": pub},
        ).scalar_one()
        assert n == 1

    def test_bulk_dedupes_within_a_batch(self, sa_sync_conn):
        """Deux annotations d'une même source visant le même sujet ne donnent qu'un lien."""
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        sent = link_publication_subjects_bulk(
            sa_sync_conn,
            source="hal",
            rows=[PublicationSubjectLink(pub, sid), PublicationSubjectLink(pub, sid)],
        )
        assert sent == 1

    def test_clear_preserves_rejected_links(self, sa_sync_conn):
        """Le nettoyage avant réingestion épargne les liens que la curation a rejetés."""
        pub = _create_pub(sa_sync_conn)
        kept = upsert_subject(sa_sync_conn, label="rejete")
        dropped = upsert_subject(sa_sync_conn, label="ordinaire")
        _link(sa_sync_conn, pub, kept, "hal")
        _link(sa_sync_conn, pub, dropped, "hal")
        sa_sync_conn.execute(
            text("UPDATE publication_subjects SET rejected = TRUE WHERE subject_id = :s"),
            {"s": kept},
        )
        assert clear_publication_subjects_for_pubs(sa_sync_conn, publication_ids=[pub]) == 1
        remaining = (
            sa_sync_conn.execute(
                text("SELECT subject_id FROM publication_subjects WHERE publication_id = :p"),
                {"p": pub},
            )
            .scalars()
            .all()
        )
        assert remaining == [kept]

    def test_subject_survives_publication_delete(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="orphan candidate")
        _link(sa_sync_conn, pub, sid, "hal")
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
