"""Sous-étape des cooccurrences de la phase `subjects` : recalcul de `usage_count` et rafraîchissement de la vue `subject_cooccurrences`."""

import logging

from sqlalchemy import text

from pipeline.transformation.publications.subjects.subject_cooccurrences import run
from pipeline.transformation.publications.subjects.subject_store import SubjectStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject


class TestRecomputeUsageCounts:
    def test_counts_distinct_publications(self, sa_sync_conn):
        s_id = insert_subject(sa_sync_conn, "ai")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        # Une publication liée au sujet par deux sources compte une fois.
        insert_publication_subject(sa_sync_conn, p1, subject_id=s_id, source="hal")
        insert_publication_subject(sa_sync_conn, p1, subject_id=s_id, source="openalex")
        insert_publication_subject(sa_sync_conn, p2, subject_id=s_id, source="hal")

        SubjectStore(sa_sync_conn).recompute_usage_counts()
        usage = sa_sync_conn.execute(
            text("SELECT usage_count FROM subjects WHERE id = :id"), {"id": s_id}
        ).scalar_one()
        assert usage == 2

    def test_resets_orphaned_subject_to_zero(self, sa_sync_conn):
        # Un sujet sans lien revient à 0.
        s_id = insert_subject(sa_sync_conn, "orphan")
        sa_sync_conn.execute(
            text("UPDATE subjects SET usage_count = 5 WHERE id = :id"), {"id": s_id}
        )
        SubjectStore(sa_sync_conn).recompute_usage_counts()
        usage = sa_sync_conn.execute(
            text("SELECT usage_count FROM subjects WHERE id = :id"), {"id": s_id}
        ).scalar_one()
        assert usage == 0


class TestRefreshCooccurrences:
    def test_pairs_with_min_count(self, sa_sync_conn):
        a = insert_subject(sa_sync_conn, "a")
        b = insert_subject(sa_sync_conn, "b")
        c = insert_subject(sa_sync_conn, "c")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        # a et b sont ensemble dans deux publications, a et c dans une seule.
        for s in (a, b):
            insert_publication_subject(sa_sync_conn, p1, subject_id=s)
        for s in (a, b, c):
            insert_publication_subject(sa_sync_conn, p2, subject_id=s)

        n = SubjectStore(sa_sync_conn).refresh_cooccurrences()
        assert n == 1  # Seule la paire (a, b) atteint le seuil de la vue.

        row = sa_sync_conn.execute(
            text("SELECT subject_a_id, subject_b_id, count FROM subject_cooccurrences")
        ).one()
        assert row.count == 2
        # Convention a < b.
        assert row.subject_a_id < row.subject_b_id
        assert {row.subject_a_id, row.subject_b_id} == {a, b}

    def test_self_pairs_excluded(self, sa_sync_conn):
        # Un sujet ne forme pas de paire avec lui-même. Deux publications le contiennent, donc le seuil de la vue laisserait passer cette paire.
        s = insert_subject(sa_sync_conn, "solo")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        insert_publication_subject(sa_sync_conn, p1, subject_id=s, source="hal")
        insert_publication_subject(sa_sync_conn, p2, subject_id=s, source="hal")

        n = SubjectStore(sa_sync_conn).refresh_cooccurrences()
        assert n == 0

    def test_idempotent(self, sa_sync_conn):
        a = insert_subject(sa_sync_conn, "a")
        b = insert_subject(sa_sync_conn, "b")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        for p in (p1, p2):
            insert_publication_subject(sa_sync_conn, p, subject_id=a)
            insert_publication_subject(sa_sync_conn, p, subject_id=b)
        SubjectStore(sa_sync_conn).refresh_cooccurrences()
        SubjectStore(sa_sync_conn).refresh_cooccurrences()
        n = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM subject_cooccurrences")
        ).scalar_one()
        assert n == 1


class TestRunOrchestrator:
    def test_full_run(self, sa_sync_conn):
        a = insert_subject(sa_sync_conn, "a")
        b = insert_subject(sa_sync_conn, "b")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        for s in (a, b):
            insert_publication_subject(sa_sync_conn, p1, subject_id=s)
            insert_publication_subject(sa_sync_conn, p2, subject_id=s)

        stats = run(SubjectStore(sa_sync_conn), logging.getLogger("test"))
        assert stats["cooccurrence_pairs"] == 1  # (a,b) count=2
        # Chacun des deux sujets est dans deux publications.
        rows = sa_sync_conn.execute(
            text("SELECT id, usage_count FROM subjects WHERE id = ANY(:ids) ORDER BY id"),
            {"ids": [a, b]},
        ).all()
        assert all(r.usage_count == 2 for r in rows)
