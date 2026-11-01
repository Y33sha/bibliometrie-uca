"""Tests d'intégration de l'écriture des sujets d'un enregistrement source (`pipeline.ingestion.common.subjects`) et du nettoyage des liens d'une publication (`subject_store`)."""

from sqlalchemy import text

from domain.subjects.subject import Subject, SubjectLink, SubjectVocabulary
from pipeline.ingestion.common.subjects import SourceRecordSubjectStore
from pipeline.transformation.publications.subjects.subject_store import SubjectStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject

_DOMAIN = Subject(SubjectVocabulary.OPENALEX, "domains/2", "Social Sciences")
_FIELD = Subject(
    SubjectVocabulary.OPENALEX, "fields/20", "Economics, Econometrics and Finance", _DOMAIN
)


def _subjects(conn):
    """Renvoie les sujets : code, libellé, niveau et code du parent, triés par niveau puis par code."""
    return conn.execute(
        text("""
            SELECT s.code, s.label, s.level, p.code AS parent_code
            FROM subjects s
            LEFT JOIN subjects p ON p.id = s.parent_id
            ORDER BY s.level, s.code
        """)
    ).all()


def _links(conn, source_record_id):
    """Renvoie les liens de l'enregistrement source : code du sujet et score, triés par code."""
    return conn.execute(
        text("""
            SELECT s.code, srs.score
            FROM source_record_subjects srs
            JOIN subjects s ON s.id = srs.subject_id
            WHERE srs.source_record_id = :id
            ORDER BY s.code
        """),
        {"id": source_record_id},
    ).all()


class TestReplaceSubjects:
    def test_writes_the_subject_with_its_ancestors(self, sa_sync_conn):
        source_record = insert_source_record(sa_sync_conn)
        SourceRecordSubjectStore(sa_sync_conn).replace_subjects(
            source_record, [SubjectLink(_FIELD, 0.5)]
        )
        assert [tuple(r) for r in _subjects(sa_sync_conn)] == [
            ("domains/2", "Social Sciences", 1, None),
            ("fields/20", "Economics, Econometrics and Finance", 2, "domains/2"),
        ]
        assert [tuple(r) for r in _links(sa_sync_conn, source_record)] == [("fields/20", 0.5)]

    def test_replaces_the_links_of_the_source_record(self, sa_sync_conn):
        source_record = insert_source_record(sa_sync_conn)
        store = SourceRecordSubjectStore(sa_sync_conn)
        store.replace_subjects(source_record, [SubjectLink(_FIELD)])
        store.replace_subjects(source_record, [SubjectLink(_DOMAIN)])
        assert [r.code for r in _links(sa_sync_conn, source_record)] == ["domains/2"]
        store.replace_subjects(source_record, [])
        assert _links(sa_sync_conn, source_record) == []

    def test_same_subject_twice_keeps_the_highest_score(self, sa_sync_conn):
        source_record = insert_source_record(sa_sync_conn)
        SourceRecordSubjectStore(sa_sync_conn).replace_subjects(
            source_record, [SubjectLink(_FIELD, 0.2), SubjectLink(_FIELD, 0.7)]
        )
        [link] = _links(sa_sync_conn, source_record)
        assert link.score == 0.7

    def test_label_follows_the_last_source_record(self, sa_sync_conn):
        first = insert_source_record(sa_sync_conn, source_id="h1")
        second = insert_source_record(sa_sync_conn, source_id="h2")
        store = SourceRecordSubjectStore(sa_sync_conn)
        store.replace_subjects(
            first, [SubjectLink(Subject(SubjectVocabulary.RAMEAU, "027266184", "Poumon -- Cancer"))]
        )
        store.replace_subjects(
            second,
            [SubjectLink(Subject(SubjectVocabulary.RAMEAU, "027266184", "Cancer du poumon"))],
        )
        assert [(r.code, r.label) for r in _subjects(sa_sync_conn)] == [
            ("027266184", "Cancer du poumon")
        ]


class TestClear:
    def test_clear_preserves_rejected_links(self, sa_sync_conn):
        """Le nettoyage avant réingestion épargne les liens rejetés à la main."""
        publication = insert_publication(sa_sync_conn)
        kept = insert_subject(sa_sync_conn, "rejete")
        dropped = insert_subject(sa_sync_conn, "ordinaire")
        insert_publication_subject(sa_sync_conn, publication, subject_id=kept)
        insert_publication_subject(sa_sync_conn, publication, subject_id=dropped)
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
        sid = insert_subject(sa_sync_conn, "orphan candidate")
        insert_publication_subject(sa_sync_conn, publication, subject_id=sid)
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
