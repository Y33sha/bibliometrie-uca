"""Tests d'intégration de la phase `cooccurrences` (recompute usage_count
+ table subject_cooccurrences)."""

import logging

from application.pipeline.cooccurrences.run import run
from infrastructure.db.queries.subjects import (
    PgSubjectsQueries,
    recompute_cooccurrences,
    recompute_usage_counts,
)


def _create_pub(db, title="X"):
    db.execute(
        "INSERT INTO publications (title, pub_year, doc_type) VALUES (%s, 2024, 'article') RETURNING id",
        (title,),
    )
    return db.fetchone()["id"]


def _create_subject(db, *, label, **kwargs):
    cols = ["label", *kwargs.keys()]
    placeholders = ", ".join(["%s"] * len(cols))
    db.execute(
        f"INSERT INTO subjects ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
        (label, *kwargs.values()),
    )
    return db.fetchone()["id"]


def _link(db, *, pub_id, subject_id, source="hal"):
    db.execute(
        "INSERT INTO publication_subjects (publication_id, subject_id, source) VALUES (%s, %s, %s)",
        (pub_id, subject_id, source),
    )


class TestRecomputeUsageCounts:
    def test_counts_distinct_publications(self, db):
        s_id = _create_subject(db, label="ai")
        p1 = _create_pub(db, "p1")
        p2 = _create_pub(db, "p2")
        # Même publi liée par 2 sources différentes : ne compte qu'une fois.
        _link(db, pub_id=p1, subject_id=s_id, source="hal")
        _link(db, pub_id=p1, subject_id=s_id, source="openalex")
        _link(db, pub_id=p2, subject_id=s_id, source="hal")

        recompute_usage_counts(db)
        db.execute("SELECT usage_count FROM subjects WHERE id = %s", (s_id,))
        assert db.fetchone()["usage_count"] == 2

    def test_resets_orphaned_subject_to_zero(self, db):
        # Sujet avec usage_count=5 mais plus aucun lien → doit retomber à 0.
        s_id = _create_subject(db, label="orphan")
        db.execute("UPDATE subjects SET usage_count = 5 WHERE id = %s", (s_id,))
        recompute_usage_counts(db)
        db.execute("SELECT usage_count FROM subjects WHERE id = %s", (s_id,))
        assert db.fetchone()["usage_count"] == 0


class TestRecomputeCooccurrences:
    def test_pairs_with_min_count(self, db):
        a = _create_subject(db, label="a")
        b = _create_subject(db, label="b")
        c = _create_subject(db, label="c")
        p1 = _create_pub(db, "p1")
        p2 = _create_pub(db, "p2")
        # a+b co-occurrent dans 2 publis ; a+c seulement 1.
        for s in (a, b):
            _link(db, pub_id=p1, subject_id=s)
        for s in (a, b, c):
            _link(db, pub_id=p2, subject_id=s)

        n = recompute_cooccurrences(db, min_count=2)
        assert n == 1  # Seule la paire (a,b) avec count=2 passe le filtre.

        db.execute("SELECT subject_a_id, subject_b_id, count FROM subject_cooccurrences")
        row = db.fetchone()
        assert row["count"] == 2
        # Convention a < b.
        assert row["subject_a_id"] < row["subject_b_id"]
        assert {row["subject_a_id"], row["subject_b_id"]} == {a, b}

    def test_self_pairs_excluded(self, db):
        # Un sujet ne co-occurre pas avec lui-même même s'il apparaît
        # plusieurs fois (deux sources sur la même publi).
        s = _create_subject(db, label="solo")
        p = _create_pub(db)
        _link(db, pub_id=p, subject_id=s, source="hal")
        _link(db, pub_id=p, subject_id=s, source="openalex")

        n = recompute_cooccurrences(db, min_count=1)
        assert n == 0

    def test_idempotent(self, db):
        a = _create_subject(db, label="a")
        b = _create_subject(db, label="b")
        p = _create_pub(db)
        _link(db, pub_id=p, subject_id=a)
        _link(db, pub_id=p, subject_id=b)
        # Une seule co-occurrence (a,b)=1 ; min=1 pour avoir 1 ligne.
        recompute_cooccurrences(db, min_count=1)
        recompute_cooccurrences(db, min_count=1)
        db.execute("SELECT count(*) AS n FROM subject_cooccurrences")
        assert db.fetchone()["n"] == 1


class TestRunOrchestrator:
    def test_full_run(self, db):
        a = _create_subject(db, label="a")
        b = _create_subject(db, label="b")
        p1 = _create_pub(db, "p1")
        p2 = _create_pub(db, "p2")
        for s in (a, b):
            _link(db, pub_id=p1, subject_id=s)
            _link(db, pub_id=p2, subject_id=s)

        stats = run(db, PgSubjectsQueries(), logging.getLogger("test"))
        assert stats["cooccurrence_pairs"] == 1  # (a,b) count=2
        # usage_count des deux sujets = 2.
        db.execute(
            "SELECT id, usage_count FROM subjects WHERE id = ANY(%s) ORDER BY id",
            ([a, b],),
        )
        rows = db.fetchall()
        assert all(r["usage_count"] == 2 for r in rows)
