"""Tests d'intégration pour `infrastructure.db.queries.subjects`."""

import pytest
from sqlalchemy import text

from infrastructure.db.queries.subjects import (
    clear_publication_subjects,
    link_publication_subject,
    upsert_subject,
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
    def test_creates_new_free(self, sa_sync_conn):
        sid = upsert_subject(sa_sync_conn, label="machine learning")
        assert sid > 0
        row = sa_sync_conn.execute(
            text("SELECT label, language, ontologies FROM subjects WHERE id = :id"), {"id": sid}
        ).one()
        assert row.label == "machine learning"
        assert row.language is None
        assert row.ontologies == {}

    def test_creates_new_concept(self, sa_sync_conn):
        sid = upsert_subject(
            sa_sync_conn,
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
        row = sa_sync_conn.execute(
            text("SELECT label, language, ontologies FROM subjects WHERE id = :id"), {"id": sid}
        ).one()
        assert row.language == "en"
        entry = row.ontologies["openalex_topic"]
        assert entry["codes"] == ["machine learning"]
        assert entry["level"] == 3
        assert entry["parent"] == "Computer Science"

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

    def test_merges_ontologies_on_conflict(self, sa_sync_conn):
        # Premier UPSERT : libre.
        a = upsert_subject(sa_sync_conn, label="biology")
        # Deuxième UPSERT : concept HAL avec le même label.
        b = upsert_subject(
            sa_sync_conn, label="biology", ontologies={"hal_domain": {"codes": ["sdv.bio"]}}
        )
        assert a == b
        onto = sa_sync_conn.execute(
            text("SELECT ontologies FROM subjects WHERE id = :id"), {"id": a}
        ).scalar_one()
        assert onto["hal_domain"]["codes"] == ["sdv.bio"]

    def test_merges_ontologies_across_sources(self, sa_sync_conn):
        sid = upsert_subject(
            sa_sync_conn, label="Informatique", ontologies={"hal_domain": {"codes": ["info"]}}
        )
        upsert_subject(
            sa_sync_conn,
            label="Informatique",
            ontologies={"theses_discipline": {"codes": ["informatique"]}},
        )
        onto = sa_sync_conn.execute(
            text("SELECT ontologies FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        assert set(onto.keys()) == {"hal_domain", "theses_discipline"}
        assert onto["hal_domain"]["codes"] == ["info"]
        assert onto["theses_discipline"]["codes"] == ["informatique"]

    def test_appends_codes_within_same_ontology(self, sa_sync_conn):
        # Même label HAL avec deux codes intra-ontologie.
        sid = upsert_subject(
            sa_sync_conn, label="Informatique", ontologies={"hal_domain": {"codes": ["info"]}}
        )
        upsert_subject(
            sa_sync_conn,
            label="Informatique",
            ontologies={"hal_domain": {"codes": ["scco.comp"]}},
        )
        onto = sa_sync_conn.execute(
            text("SELECT ontologies FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        assert sorted(onto["hal_domain"]["codes"]) == ["info", "scco.comp"]

    def test_idempotent_same_ontology_code(self, sa_sync_conn):
        sid = upsert_subject(sa_sync_conn, label="X", ontologies={"hal_domain": {"codes": ["a"]}})
        upsert_subject(sa_sync_conn, label="X", ontologies={"hal_domain": {"codes": ["a"]}})
        onto = sa_sync_conn.execute(
            text("SELECT ontologies FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        assert onto["hal_domain"]["codes"] == ["a"]

    def test_level_and_parent_per_ontology(self, sa_sync_conn):
        # Le level/parent sont stockés dans le JSONB, par ontologie.
        sid = upsert_subject(
            sa_sync_conn,
            label="Medicine",
            ontologies={
                "openalex_topic": {
                    "codes": ["medicine"],
                    "level": 1,
                    "parent": "Health Sciences",
                }
            },
        )
        onto = sa_sync_conn.execute(
            text("SELECT ontologies FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        entry = onto["openalex_topic"]
        assert entry["level"] == 1
        assert entry["parent"] == "Health Sciences"

    def test_first_non_null_level_parent_wins(self, sa_sync_conn):
        # Premier UPSERT pose level=2, parent="Engineering".
        sid = upsert_subject(
            sa_sync_conn,
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
            sa_sync_conn,
            label="Computer Science",
            ontologies={
                "openalex_topic": {
                    "codes": ["computer science"],
                    "level": 1,
                    "parent": "Other",
                }
            },
        )
        onto = sa_sync_conn.execute(
            text("SELECT ontologies FROM subjects WHERE id = :id"), {"id": sid}
        ).scalar_one()
        entry = onto["openalex_topic"]
        assert entry["level"] == 2
        assert entry["parent"] == "Engineering"


class TestLinkAndClear:
    def test_link_creates_row(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="hal", score=None
        )
        row = sa_sync_conn.execute(
            text(
                "SELECT source, score FROM publication_subjects "
                "WHERE publication_id = :p AND subject_id = :s"
            ),
            {"p": pub, "s": sid},
        ).one()
        assert row.source == "hal"
        assert row.score is None

    def test_link_same_subject_two_sources(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(sa_sync_conn, publication_id=pub, subject_id=sid, source="hal")
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex"
        )
        n = sa_sync_conn.execute(
            text("SELECT count(*) AS n FROM publication_subjects WHERE publication_id = :p"),
            {"p": pub},
        ).scalar_one()
        assert n == 2

    def test_link_same_source_updates_score(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex", score=0.5
        )
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex", score=0.8
        )
        score = sa_sync_conn.execute(
            text(
                "SELECT score FROM publication_subjects "
                "WHERE publication_id = :p AND subject_id = :s AND source = 'openalex'"
            ),
            {"p": pub, "s": sid},
        ).scalar_one()
        assert score == pytest.approx(0.8)

    def test_clear_only_removes_target_source(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="x")
        link_publication_subject(sa_sync_conn, publication_id=pub, subject_id=sid, source="hal")
        link_publication_subject(
            sa_sync_conn, publication_id=pub, subject_id=sid, source="openalex"
        )
        n = clear_publication_subjects(sa_sync_conn, publication_id=pub, source="hal")
        assert n == 1
        sources = (
            sa_sync_conn.execute(
                text("SELECT source FROM publication_subjects WHERE publication_id = :p"),
                {"p": pub},
            )
            .scalars()
            .all()
        )
        assert sources == ["openalex"]

    def test_subject_survives_publication_delete(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sid = upsert_subject(sa_sync_conn, label="orphan candidate")
        link_publication_subject(sa_sync_conn, publication_id=pub, subject_id=sid, source="hal")
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
