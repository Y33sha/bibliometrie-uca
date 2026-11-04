"""Sous-étape des cooccurrences de la phase `subjects` : recalcul de `usage_count` et rafraîchissement des vues `subject_labels` et `subject_cooccurrences`."""

import logging

from sqlalchemy import text

from domain.subjects.subject import SubjectVocabulary
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


class TestRefreshLabels:
    def test_union_of_publications_across_vocabularies(self, sa_sync_conn):
        hal = insert_subject(sa_sync_conn, "Chimie", vocabulary=SubjectVocabulary.HAL_DOMAIN)
        rameau = insert_subject(
            sa_sync_conn, "chimie", vocabulary=SubjectVocabulary.RAMEAU, code="027249808"
        )
        p1, p2, p3 = (insert_publication(sa_sync_conn, f"p{i}") for i in (1, 2, 3))
        for p in (p1, p2):
            insert_publication_subject(sa_sync_conn, p, subject_id=hal, source="hal")
        # p2 a les deux sujets : elle compte une fois.
        for p in (p2, p3):
            insert_publication_subject(sa_sync_conn, p, subject_id=rameau, source="theses")

        assert SubjectStore(sa_sync_conn).refresh_labels() == 1
        row = sa_sync_conn.execute(
            text("SELECT label_normalized, usage_count FROM subject_labels")
        ).one()
        assert (row.label_normalized, row.usage_count) == ("chimie", 3)

    def test_most_frequent_form(self, sa_sync_conn):
        rare = insert_subject(sa_sync_conn, "Sciences Economiques", code="a")
        frequent = insert_subject(sa_sync_conn, "Sciences économiques", code="b")
        p1 = insert_publication(sa_sync_conn, "p1")
        p2 = insert_publication(sa_sync_conn, "p2")
        insert_publication_subject(sa_sync_conn, p1, subject_id=rare)
        for p in (p1, p2):
            insert_publication_subject(sa_sync_conn, p, subject_id=frequent)

        SubjectStore(sa_sync_conn).refresh_labels()
        label = sa_sync_conn.execute(text("SELECT label FROM subject_labels")).scalar_one()
        assert label == "Sciences économiques"


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
            text("SELECT label_a, label_b, count FROM subject_cooccurrences")
        ).one()
        assert (row.label_a, row.label_b, row.count) == ("a", "b", 2)

    def test_same_label_forms_no_pair(self, sa_sync_conn):
        # Deux sujets de même libellé normalisé forment un seul libellé, sans paire entre eux.
        hal = insert_subject(sa_sync_conn, "Chimie", vocabulary=SubjectVocabulary.HAL_DOMAIN)
        rameau = insert_subject(sa_sync_conn, "Chimie", vocabulary=SubjectVocabulary.RAMEAU)
        for p in (insert_publication(sa_sync_conn, "p1"), insert_publication(sa_sync_conn, "p2")):
            insert_publication_subject(sa_sync_conn, p, subject_id=hal, source="hal")
            insert_publication_subject(sa_sync_conn, p, subject_id=rameau, source="theses")

        assert SubjectStore(sa_sync_conn).refresh_cooccurrences() == 0

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

        run(sa_sync_conn, logging.getLogger("test"))
        assert sa_sync_conn.execute(text("SELECT count(*) FROM subject_labels")).scalar_one() == 2
        # Paire (a, b), présente dans deux publications.
        assert (
            sa_sync_conn.execute(text("SELECT count(*) FROM subject_cooccurrences")).scalar_one()
            == 1
        )
        # Chacun des deux sujets est dans deux publications.
        rows = sa_sync_conn.execute(
            text("SELECT id, usage_count FROM subjects WHERE id = ANY(:ids) ORDER BY id"),
            {"ids": [a, b]},
        ).all()
        assert all(r.usage_count == 2 for r in rows)
