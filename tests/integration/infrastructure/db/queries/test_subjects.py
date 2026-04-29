"""Tests d'intégration pour `infrastructure.db.queries.subjects`."""

import psycopg.errors
import pytest

from infrastructure.db.queries.subjects import (
    clear_publication_subjects,
    link_publication_subject,
    upsert_concept_subject,
    upsert_free_subject,
)


def _create_pub(db, title="X"):
    db.execute(
        "INSERT INTO publications (title, pub_year, doc_type) VALUES (%s, 2024, 'article') RETURNING id",
        (title,),
    )
    return db.fetchone()["id"]


class TestUpsertFreeSubject:
    def test_creates_new_free(self, db):
        sid = upsert_free_subject(db, label="machine learning", language="en")
        assert sid > 0
        db.execute("SELECT kind, label, language, ontology FROM subjects WHERE id = %s", (sid,))
        row = db.fetchone()
        assert row["kind"] == "free"
        assert row["label"] == "machine learning"
        assert row["language"] == "en"
        assert row["ontology"] is None

    def test_dedup_case_insensitive(self, db):
        a = upsert_free_subject(db, label="Machine Learning", language="en")
        b = upsert_free_subject(db, label="machine learning", language="en")
        assert a == b
        # La casse originale est conservée (premier insert).
        db.execute("SELECT label FROM subjects WHERE id = %s", (a,))
        assert db.fetchone()["label"] == "Machine Learning"

    def test_distinct_languages_are_distinct(self, db):
        en = upsert_free_subject(db, label="biology", language="en")
        fr = upsert_free_subject(db, label="biology", language="fr")
        assert en != fr

    def test_null_language_is_dedup_key(self, db):
        a = upsert_free_subject(db, label="biology", language=None)
        b = upsert_free_subject(db, label="biology", language=None)
        assert a == b
        # Mais distinct d'un libre avec langue spécifiée.
        c = upsert_free_subject(db, label="biology", language="en")
        assert c != a

    def test_normalizes_whitespace(self, db):
        a = upsert_free_subject(db, label="  machine    learning  ", language="en")
        b = upsert_free_subject(db, label="machine learning", language="en")
        assert a == b


class TestUpsertConceptSubject:
    def test_creates_new_concept(self, db):
        sid = upsert_concept_subject(
            db,
            ontology="openalex_topic",
            ontology_id="T10138",
            label="Machine Learning Applications",
            language="en",
            level=3,
        )
        db.execute(
            "SELECT kind, ontology, ontology_id, label, level FROM subjects WHERE id = %s",
            (sid,),
        )
        row = db.fetchone()
        assert row["kind"] == "concept"
        assert row["ontology"] == "openalex_topic"
        assert row["ontology_id"] == "T10138"
        assert row["level"] == 3

    def test_dedup_on_ontology_pair(self, db):
        a = upsert_concept_subject(
            db, ontology="hal_domain", ontology_id="info.eea", label="Sciences EEA"
        )
        b = upsert_concept_subject(
            db, ontology="hal_domain", ontology_id="info.eea", label="Sciences EEA (mis à jour)"
        )
        assert a == b
        # Le label est rafraîchi.
        db.execute("SELECT label FROM subjects WHERE id = %s", (a,))
        assert db.fetchone()["label"] == "Sciences EEA (mis à jour)"

    def test_concept_and_free_with_same_label_are_distinct(self, db):
        free = upsert_free_subject(db, label="biology", language="en")
        concept = upsert_concept_subject(
            db, ontology="wos_subject", ontology_id="biology", label="Biology"
        )
        assert free != concept

    def test_parent_id_self_reference(self, db):
        domain = upsert_concept_subject(
            db, ontology="openalex_topic", ontology_id="D1", label="Health Sciences", level=0
        )
        field = upsert_concept_subject(
            db,
            ontology="openalex_topic",
            ontology_id="F11",
            label="Medicine",
            level=1,
            parent_id=domain,
        )
        db.execute("SELECT parent_id, level FROM subjects WHERE id = %s", (field,))
        row = db.fetchone()
        assert row["parent_id"] == domain
        assert row["level"] == 1


class TestLinkAndClear:
    def test_link_creates_row(self, db):
        pub = _create_pub(db)
        sid = upsert_free_subject(db, label="x")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="hal", score=None)
        db.execute(
            "SELECT source, score FROM publication_subjects WHERE publication_id = %s AND subject_id = %s",
            (pub, sid),
        )
        row = db.fetchone()
        assert row["source"] == "hal"
        assert row["score"] is None

    def test_link_same_subject_two_sources(self, db):
        pub = _create_pub(db)
        sid = upsert_free_subject(db, label="x")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="hal")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="openalex")
        db.execute(
            "SELECT count(*) AS n FROM publication_subjects WHERE publication_id = %s",
            (pub,),
        )
        assert db.fetchone()["n"] == 2

    def test_link_same_source_updates_score(self, db):
        pub = _create_pub(db)
        sid = upsert_free_subject(db, label="x")
        link_publication_subject(
            db, publication_id=pub, subject_id=sid, source="openalex", score=0.5
        )
        link_publication_subject(
            db, publication_id=pub, subject_id=sid, source="openalex", score=0.8
        )
        db.execute(
            "SELECT score FROM publication_subjects WHERE publication_id = %s AND subject_id = %s AND source = 'openalex'",
            (pub, sid),
        )
        assert db.fetchone()["score"] == pytest.approx(0.8)

    def test_clear_only_removes_target_source(self, db):
        pub = _create_pub(db)
        sid = upsert_free_subject(db, label="x")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="hal")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="openalex")
        n = clear_publication_subjects(db, publication_id=pub, source="hal")
        assert n == 1
        db.execute(
            "SELECT source FROM publication_subjects WHERE publication_id = %s",
            (pub,),
        )
        rows = db.fetchall()
        assert [r["source"] for r in rows] == ["openalex"]

    def test_subject_survives_publication_delete(self, db):
        # ON DELETE CASCADE sur publication_subjects, mais subjects reste.
        pub = _create_pub(db)
        sid = upsert_free_subject(db, label="orphan candidate")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="hal")
        db.execute("DELETE FROM publications WHERE id = %s", (pub,))
        db.execute("SELECT count(*) AS n FROM publication_subjects WHERE subject_id = %s", (sid,))
        assert db.fetchone()["n"] == 0
        db.execute("SELECT count(*) AS n FROM subjects WHERE id = %s", (sid,))
        assert db.fetchone()["n"] == 1


class TestSchemaConstraints:
    def test_concept_must_have_ontology(self, db):
        # CHECK subjects_concept_has_ontology empêche un concept sans ontology.
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute("INSERT INTO subjects (kind, label) VALUES ('concept', 'orphelin')")

    def test_free_must_not_have_ontology(self, db):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "INSERT INTO subjects (kind, label, ontology, ontology_id) "
                "VALUES ('free', 'x', 'hal_domain', 'foo')"
            )
