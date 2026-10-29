"""Tests d'intégration pour `pipeline.transformation.publications.subjects.subject_store`."""

from sqlalchemy import text

from pipeline.transformation.publications.subjects.subject_store import (
    PublicationSubjectLink,
    SubjectStore,
)
from tests.integration.helpers.publications import insert_publication


def _link(conn, publication_id, subject_id, source):
    return SubjectStore(conn).link_publication_subjects_bulk(
        source=source, rows=[PublicationSubjectLink(publication_id, subject_id)]
    )


class TestUpsertSubject:
    def test_creates_new(self, sa_sync_conn):
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="machine learning")
        assert sid > 0
        row = sa_sync_conn.execute(
            text("SELECT label, language FROM subjects WHERE id = :id"), {"id": sid}
        ).one()
        assert row.label == "machine learning"
        assert row.language is None

    def test_stores_language(self, sa_sync_conn):
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="Machine Learning", language="en")
        language = sa_sync_conn.execute(
            text("SELECT language FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        assert language == "en"

    def test_dedup_case_insensitive(self, sa_sync_conn):
        a = SubjectStore(sa_sync_conn).upsert_subject(label="Machine Learning")
        b = SubjectStore(sa_sync_conn).upsert_subject(label="machine learning")
        assert a == b
        # La casse originale est conservée.
        label = sa_sync_conn.execute(
            text("SELECT label FROM subjects WHERE id = :id"), {"id": a}
        ).scalar_one()
        assert label == "Machine Learning"

    def test_normalizes_whitespace(self, sa_sync_conn):
        a = SubjectStore(sa_sync_conn).upsert_subject(label="  machine    learning  ")
        b = SubjectStore(sa_sync_conn).upsert_subject(label="machine learning")
        assert a == b

    def test_language_first_non_null_wins(self, sa_sync_conn):
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="Biology", language="en")
        SubjectStore(sa_sync_conn).upsert_subject(label="biology", language="fr")
        language = sa_sync_conn.execute(
            text("SELECT language FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        assert language == "en"


class TestLinkAndClear:
    def test_link_creates_row(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="x")
        _link(sa_sync_conn, publication, sid, "hal")
        source = sa_sync_conn.execute(
            text(
                "SELECT source FROM publication_subjects "
                "WHERE publication_id = :p AND subject_id = :s"
            ),
            {"p": publication, "s": sid},
        ).scalar_one()
        assert source == "hal"

    def test_link_same_subject_two_sources(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="x")
        _link(sa_sync_conn, publication, sid, "hal")
        _link(sa_sync_conn, publication, sid, "openalex")
        n = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM publication_subjects WHERE publication_id = :p"),
            {"p": publication},
        ).scalar_one()
        assert n == 2

    def test_link_idempotent_same_source(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="x")
        _link(sa_sync_conn, publication, sid, "openalex")
        _link(sa_sync_conn, publication, sid, "openalex")
        n = sa_sync_conn.execute(
            text(
                "SELECT count(*) AS n FROM publication_subjects "
                "WHERE publication_id = :p AND source = 'openalex'"
            ),
            {"p": publication},
        ).scalar_one()
        assert n == 1

    def test_bulk_dedupes_within_a_batch(self, sa_sync_conn):
        """Deux annotations d'une même source pour le même sujet donnent un seul lien."""
        publication = insert_publication(sa_sync_conn)
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="x")
        sent = SubjectStore(sa_sync_conn).link_publication_subjects_bulk(
            source="hal",
            rows=[
                PublicationSubjectLink(publication, sid),
                PublicationSubjectLink(publication, sid),
            ],
        )
        assert sent == 1

    def test_bulk_counts_only_new_links(self, sa_sync_conn):
        """La valeur rendue compte les liens insérés, pas ceux déjà présents."""
        publication = insert_publication(sa_sync_conn)
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="x")
        sid2 = SubjectStore(sa_sync_conn).upsert_subject(label="y")
        SubjectStore(sa_sync_conn).link_publication_subjects_bulk(
            source="hal", rows=[PublicationSubjectLink(publication, sid)]
        )
        # Le lien existant et un lien absent : seul le second compte.
        n = SubjectStore(sa_sync_conn).link_publication_subjects_bulk(
            source="hal",
            rows=[
                PublicationSubjectLink(publication, sid),
                PublicationSubjectLink(publication, sid2),
            ],
        )
        assert n == 1

    def test_clear_preserves_rejected_links(self, sa_sync_conn):
        """Le nettoyage avant réingestion épargne les liens rejetés à la main."""
        publication = insert_publication(sa_sync_conn)
        kept = SubjectStore(sa_sync_conn).upsert_subject(label="rejete")
        dropped = SubjectStore(sa_sync_conn).upsert_subject(label="ordinaire")
        _link(sa_sync_conn, publication, kept, "hal")
        _link(sa_sync_conn, publication, dropped, "hal")
        sa_sync_conn.execute(
            text("UPDATE publication_subjects SET rejected = TRUE WHERE subject_id = :s"),
            {"s": kept},
        )
        assert (
            SubjectStore(sa_sync_conn).clear_publication_subjects_for_publications(
                publication_ids=[publication]
            )
            == 1
        )
        remaining = (
            sa_sync_conn.execute(
                text("SELECT subject_id FROM publication_subjects WHERE publication_id = :p"),
                {"p": publication},
            )
            .scalars()
            .all()
        )
        assert remaining == [kept]

    def test_subject_survives_publication_delete(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        sid = SubjectStore(sa_sync_conn).upsert_subject(label="orphan candidate")
        _link(sa_sync_conn, publication, sid, "hal")
        sa_sync_conn.execute(text("DELETE FROM publications WHERE id = :p"), {"p": publication})
        n_links = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM publication_subjects WHERE subject_id = :s"),
            {"s": sid},
        ).scalar_one()
        assert n_links == 0
        n_subj = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM subjects WHERE id = :s"), {"s": sid}
        ).scalar_one()
        assert n_subj == 1
