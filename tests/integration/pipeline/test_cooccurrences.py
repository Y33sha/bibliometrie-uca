"""Tests d'intégration de la sous-étape cooccurrences de la phase `subjects` (recompute
usage_count + refresh matview subject_cooccurrences)."""

import logging

from sqlalchemy import text

from pipeline.transformation.publications.subjects.subject_cooccurrences import run
from pipeline.transformation.publications.subjects.subjects_queries import SubjectsIngestionQueries
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject

_Q = SubjectsIngestionQueries()


class TestRecomputeUsageCounts:
    def test_counts_distinct_publications(self, sa_sync_conn):
        s_id = insert_subject(sa_sync_conn, "ai")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        # Même publi liée par 2 sources différentes : ne compte qu'une fois.
        insert_publication_subject(sa_sync_conn, p1, subject_id=s_id, source="hal")
        insert_publication_subject(sa_sync_conn, p1, subject_id=s_id, source="openalex")
        insert_publication_subject(sa_sync_conn, p2, subject_id=s_id, source="hal")

        _Q.recompute_usage_counts(sa_sync_conn)
        usage = sa_sync_conn.execute(
            text("SELECT usage_count FROM subjects WHERE id = :id"), {"id": s_id}
        ).scalar_one()
        assert usage == 2

    def test_resets_orphaned_subject_to_zero(self, sa_sync_conn):
        # Sujet avec usage_count=5 mais plus aucun lien → doit retomber à 0.
        s_id = insert_subject(sa_sync_conn, "orphan")
        sa_sync_conn.execute(
            text("UPDATE subjects SET usage_count = 5 WHERE id = :id"), {"id": s_id}
        )
        _Q.recompute_usage_counts(sa_sync_conn)
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
        # a+b co-occurrent dans 2 publis ; a+c seulement 1.
        for s in (a, b):
            insert_publication_subject(sa_sync_conn, p1, subject_id=s)
        for s in (a, b, c):
            insert_publication_subject(sa_sync_conn, p2, subject_id=s)

        n = _Q.refresh_cooccurrences(sa_sync_conn)
        assert n == 1  # Seule la paire (a,b) avec count=2 passe le seuil de la matview.

        row = sa_sync_conn.execute(
            text("SELECT subject_a_id, subject_b_id, count FROM subject_cooccurrences")
        ).one()
        assert row.count == 2
        # Convention a < b.
        assert row.subject_a_id < row.subject_b_id
        assert {row.subject_a_id, row.subject_b_id} == {a, b}

    def test_self_pairs_excluded(self, sa_sync_conn):
        # Un sujet ne co-occurre pas avec lui-même même s'il apparaît dans
        # 2+ publications (deux publications nécessaires pour que le seuil count >= 2
        # ne masque pas l'effet du filtre `subject_id < subject_id`).
        s = insert_subject(sa_sync_conn, "solo")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        insert_publication_subject(sa_sync_conn, p1, subject_id=s, source="hal")
        insert_publication_subject(sa_sync_conn, p2, subject_id=s, source="hal")

        n = _Q.refresh_cooccurrences(sa_sync_conn)
        assert n == 0

    def test_idempotent(self, sa_sync_conn):
        a = insert_subject(sa_sync_conn, "a")
        b = insert_subject(sa_sync_conn, "b")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        for p in (p1, p2):
            insert_publication_subject(sa_sync_conn, p, subject_id=a)
            insert_publication_subject(sa_sync_conn, p, subject_id=b)
        _Q.refresh_cooccurrences(sa_sync_conn)
        _Q.refresh_cooccurrences(sa_sync_conn)
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

        stats = run(sa_sync_conn, SubjectsIngestionQueries(), logging.getLogger("test"))
        assert stats["cooccurrence_pairs"] == 1  # (a,b) count=2
        # usage_count des deux sujets = 2.
        rows = sa_sync_conn.execute(
            text("SELECT id, usage_count FROM subjects WHERE id = ANY(:ids) ORDER BY id"),
            {"ids": [a, b]},
        ).all()
        assert all(r.usage_count == 2 for r in rows)
