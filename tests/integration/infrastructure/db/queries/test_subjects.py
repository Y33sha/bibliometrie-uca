"""Tests d'intégration pour `infrastructure.db.queries.subjects`."""

import pytest

from infrastructure.db.queries.subjects import (
    clear_publication_subjects,
    link_publication_subject,
    upsert_subject,
)


def _create_pub(db, title="X"):
    db.execute(
        "INSERT INTO publications (title, pub_year, doc_type) VALUES (%s, 2024, 'article') RETURNING id",
        (title,),
    )
    return db.fetchone()["id"]


class TestUpsertSubject:
    def test_creates_new_free(self, db):
        sid = upsert_subject(db, label="machine learning")
        assert sid > 0
        db.execute("SELECT label, language, ontologies FROM subjects WHERE id = %s", (sid,))
        row = db.fetchone()
        assert row["label"] == "machine learning"
        assert row["language"] is None
        assert row["ontologies"] == {}

    def test_creates_new_concept(self, db):
        sid = upsert_subject(
            db,
            label="Machine Learning",
            language="en",
            ontologies={
                "openalex_topic": {
                    "codes": ["machine learning"],
                    "level": 3,
                    "parent": "Computer Science",
                }
            },
        )
        db.execute("SELECT label, language, ontologies FROM subjects WHERE id = %s", (sid,))
        row = db.fetchone()
        assert row["language"] == "en"
        entry = row["ontologies"]["openalex_topic"]
        assert entry["codes"] == ["machine learning"]
        assert entry["level"] == 3
        assert entry["parent"] == "Computer Science"

    def test_dedup_case_insensitive(self, db):
        a = upsert_subject(db, label="Machine Learning")
        b = upsert_subject(db, label="machine learning")
        assert a == b
        # La casse originale est conservée.
        db.execute("SELECT label FROM subjects WHERE id = %s", (a,))
        assert db.fetchone()["label"] == "Machine Learning"

    def test_normalizes_whitespace(self, db):
        a = upsert_subject(db, label="  machine    learning  ")
        b = upsert_subject(db, label="machine learning")
        assert a == b

    def test_merges_ontologies_on_conflict(self, db):
        # Premier UPSERT : libre.
        a = upsert_subject(db, label="biology")
        # Deuxième UPSERT : concept HAL avec le même label.
        b = upsert_subject(db, label="biology", ontologies={"hal_domain": {"codes": ["sdv.bio"]}})
        assert a == b
        db.execute("SELECT ontologies FROM subjects WHERE id = %s", (a,))
        onto = db.fetchone()["ontologies"]
        assert onto["hal_domain"]["codes"] == ["sdv.bio"]

    def test_merges_ontologies_across_sources(self, db):
        sid = upsert_subject(
            db, label="Informatique", ontologies={"hal_domain": {"codes": ["info"]}}
        )
        upsert_subject(
            db,
            label="Informatique",
            ontologies={"theses_discipline": {"codes": ["informatique"]}},
        )
        db.execute("SELECT ontologies FROM subjects WHERE id = %s", (sid,))
        onto = db.fetchone()["ontologies"]
        assert set(onto.keys()) == {"hal_domain", "theses_discipline"}
        assert onto["hal_domain"]["codes"] == ["info"]
        assert onto["theses_discipline"]["codes"] == ["informatique"]

    def test_appends_codes_within_same_ontology(self, db):
        # Même label HAL avec deux codes intra-ontologie.
        sid = upsert_subject(
            db, label="Informatique", ontologies={"hal_domain": {"codes": ["info"]}}
        )
        upsert_subject(
            db, label="Informatique", ontologies={"hal_domain": {"codes": ["scco.comp"]}}
        )
        db.execute("SELECT ontologies FROM subjects WHERE id = %s", (sid,))
        onto = db.fetchone()["ontologies"]
        assert sorted(onto["hal_domain"]["codes"]) == ["info", "scco.comp"]

    def test_idempotent_same_ontology_code(self, db):
        sid = upsert_subject(db, label="X", ontologies={"hal_domain": {"codes": ["a"]}})
        upsert_subject(db, label="X", ontologies={"hal_domain": {"codes": ["a"]}})
        db.execute("SELECT ontologies FROM subjects WHERE id = %s", (sid,))
        assert db.fetchone()["ontologies"]["hal_domain"]["codes"] == ["a"]

    def test_level_and_parent_per_ontology(self, db):
        # Le level/parent sont stockés dans le JSONB, par ontologie.
        sid = upsert_subject(
            db,
            label="Medicine",
            ontologies={
                "openalex_topic": {
                    "codes": ["medicine"],
                    "level": 1,
                    "parent": "Health Sciences",
                }
            },
        )
        db.execute("SELECT ontologies FROM subjects WHERE id = %s", (sid,))
        entry = db.fetchone()["ontologies"]["openalex_topic"]
        assert entry["level"] == 1
        assert entry["parent"] == "Health Sciences"

    def test_first_non_null_level_parent_wins(self, db):
        # Premier UPSERT pose level=2, parent="Engineering".
        sid = upsert_subject(
            db,
            label="Computer Science",
            ontologies={
                "openalex_topic": {
                    "codes": ["computer science"],
                    "level": 2,
                    "parent": "Engineering",
                }
            },
        )
        # Deuxième UPSERT avec level=1, parent="Other" : ne devrait PAS écraser.
        upsert_subject(
            db,
            label="Computer Science",
            ontologies={
                "openalex_topic": {
                    "codes": ["computer science"],
                    "level": 1,
                    "parent": "Other",
                }
            },
        )
        db.execute("SELECT ontologies FROM subjects WHERE id = %s", (sid,))
        entry = db.fetchone()["ontologies"]["openalex_topic"]
        assert entry["level"] == 2
        assert entry["parent"] == "Engineering"


class TestLinkAndClear:
    def test_link_creates_row(self, db):
        pub = _create_pub(db)
        sid = upsert_subject(db, label="x")
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
        sid = upsert_subject(db, label="x")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="hal")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="openalex")
        db.execute(
            "SELECT count(*) AS n FROM publication_subjects WHERE publication_id = %s",
            (pub,),
        )
        assert db.fetchone()["n"] == 2

    def test_link_same_source_updates_score(self, db):
        pub = _create_pub(db)
        sid = upsert_subject(db, label="x")
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
        sid = upsert_subject(db, label="x")
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
        pub = _create_pub(db)
        sid = upsert_subject(db, label="orphan candidate")
        link_publication_subject(db, publication_id=pub, subject_id=sid, source="hal")
        db.execute("DELETE FROM publications WHERE id = %s", (pub,))
        db.execute("SELECT count(*) AS n FROM publication_subjects WHERE subject_id = %s", (sid,))
        assert db.fetchone()["n"] == 0
        db.execute("SELECT count(*) AS n FROM subjects WHERE id = %s", (sid,))
        assert db.fetchone()["n"] == 1
