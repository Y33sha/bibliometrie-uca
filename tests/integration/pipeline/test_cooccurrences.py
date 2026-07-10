"""Tests d'intégration de la sous-étape cooccurrences de la phase `subjects` (recompute
usage_count + refresh matview subject_cooccurrences)."""

import logging

from sqlalchemy import text

from application.pipeline.subjects.cooccurrences import run
from infrastructure.queries.subjects import (
    PgSubjectsQueries,
    recompute_usage_counts,
    refresh_cooccurrences,
)


def _create_pub(conn, title="X"):
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, doc_type) "
            "VALUES (:t, 2024, 'article') RETURNING id"
        ),
        {"t": title},
    ).scalar_one()


def _create_subject(conn, *, label, **kwargs):
    cols = ["label", *kwargs.keys()]
    placeholders = ", ".join([f":{c}" for c in cols])
    binds = {"label": label, **kwargs}
    return conn.execute(
        text(f"INSERT INTO subjects ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id"),
        binds,
    ).scalar_one()


def _link(conn, *, pub_id, subject_id, source="hal"):
    conn.execute(
        text(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) "
            "VALUES (:p, :s, :src)"
        ),
        {"p": pub_id, "s": subject_id, "src": source},
    )


class TestRecomputeUsageCounts:
    def test_counts_distinct_publications(self, sa_sync_conn):
        s_id = _create_subject(sa_sync_conn, label="ai")
        p1 = _create_pub(sa_sync_conn, "p1")
        p2 = _create_pub(sa_sync_conn, "p2")
        # Même publi liée par 2 sources différentes : ne compte qu'une fois.
        _link(sa_sync_conn, pub_id=p1, subject_id=s_id, source="hal")
        _link(sa_sync_conn, pub_id=p1, subject_id=s_id, source="openalex")
        _link(sa_sync_conn, pub_id=p2, subject_id=s_id, source="hal")

        recompute_usage_counts(sa_sync_conn)
        usage = sa_sync_conn.execute(
            text("SELECT usage_count FROM subjects WHERE id = :id"), {"id": s_id}
        ).scalar_one()
        assert usage == 2

    def test_resets_orphaned_subject_to_zero(self, sa_sync_conn):
        # Sujet avec usage_count=5 mais plus aucun lien → doit retomber à 0.
        s_id = _create_subject(sa_sync_conn, label="orphan")
        sa_sync_conn.execute(
            text("UPDATE subjects SET usage_count = 5 WHERE id = :id"), {"id": s_id}
        )
        recompute_usage_counts(sa_sync_conn)
        usage = sa_sync_conn.execute(
            text("SELECT usage_count FROM subjects WHERE id = :id"), {"id": s_id}
        ).scalar_one()
        assert usage == 0


class TestRefreshCooccurrences:
    def test_pairs_with_min_count(self, sa_sync_conn):
        a = _create_subject(sa_sync_conn, label="a")
        b = _create_subject(sa_sync_conn, label="b")
        c = _create_subject(sa_sync_conn, label="c")
        p1 = _create_pub(sa_sync_conn, "p1")
        p2 = _create_pub(sa_sync_conn, "p2")
        # a+b co-occurrent dans 2 publis ; a+c seulement 1.
        for s in (a, b):
            _link(sa_sync_conn, pub_id=p1, subject_id=s)
        for s in (a, b, c):
            _link(sa_sync_conn, pub_id=p2, subject_id=s)

        n = refresh_cooccurrences(sa_sync_conn)
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
        # 2+ publications (deux pubs nécessaires pour que le seuil count >= 2
        # ne masque pas l'effet du filtre `subject_id < subject_id`).
        s = _create_subject(sa_sync_conn, label="solo")
        p1 = _create_pub(sa_sync_conn, "p1")
        p2 = _create_pub(sa_sync_conn, "p2")
        _link(sa_sync_conn, pub_id=p1, subject_id=s, source="hal")
        _link(sa_sync_conn, pub_id=p2, subject_id=s, source="hal")

        n = refresh_cooccurrences(sa_sync_conn)
        assert n == 0

    def test_idempotent(self, sa_sync_conn):
        a = _create_subject(sa_sync_conn, label="a")
        b = _create_subject(sa_sync_conn, label="b")
        p1 = _create_pub(sa_sync_conn, "p1")
        p2 = _create_pub(sa_sync_conn, "p2")
        for p in (p1, p2):
            _link(sa_sync_conn, pub_id=p, subject_id=a)
            _link(sa_sync_conn, pub_id=p, subject_id=b)
        refresh_cooccurrences(sa_sync_conn)
        refresh_cooccurrences(sa_sync_conn)
        n = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM subject_cooccurrences")
        ).scalar_one()
        assert n == 1


class TestRunOrchestrator:
    def test_full_run(self, sa_sync_conn):
        a = _create_subject(sa_sync_conn, label="a")
        b = _create_subject(sa_sync_conn, label="b")
        p1 = _create_pub(sa_sync_conn, "p1")
        p2 = _create_pub(sa_sync_conn, "p2")
        for s in (a, b):
            _link(sa_sync_conn, pub_id=p1, subject_id=s)
            _link(sa_sync_conn, pub_id=p2, subject_id=s)

        stats = run(sa_sync_conn, PgSubjectsQueries(), logging.getLogger("test"))
        assert stats["cooccurrence_pairs"] == 1  # (a,b) count=2
        # usage_count des deux sujets = 2.
        rows = sa_sync_conn.execute(
            text("SELECT id, usage_count FROM subjects WHERE id = ANY(:ids) ORDER BY id"),
            {"ids": [a, b]},
        ).all()
        assert all(r.usage_count == 2 for r in rows)
