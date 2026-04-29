"""Tests d'intégration des ingestors `application/pipeline/subjects/*`
et de l'orchestrateur `run.py`."""

import logging

import pytest
from psycopg.types.json import Json

from application.pipeline.subjects import (
    ingest_crossref,
    ingest_hal,
    ingest_openalex,
    ingest_scanr,
    ingest_theses,
    ingest_wos,
)
from application.pipeline.subjects._common import SubjectCache
from application.pipeline.subjects.run import run
from infrastructure.db.queries.subjects import PgSubjectsQueries


@pytest.fixture
def cache():
    return SubjectCache(PgSubjectsQueries())


@pytest.fixture
def queries():
    return PgSubjectsQueries()


def _create_pub(db, title="X"):
    db.execute(
        "INSERT INTO publications (title, pub_year, doc_type) VALUES (%s, 2024, 'article') RETURNING id",
        (title,),
    )
    return db.fetchone()["id"]


def _create_source_pub(db, *, source, source_id, publication_id, keywords=None, topics=None):
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, publication_id, keywords, topics)
        VALUES (%s, %s, 'X', %s, %s, %s) RETURNING id
        """,
        (source, source_id, publication_id, keywords, Json(topics) if topics is not None else None),
    )
    return db.fetchone()["id"]


def _subjects_of(db, pub_id):
    db.execute(
        """
        SELECT s.kind, s.label, s.ontology, s.ontology_id, s.parent_id, s.level, ps.score
        FROM publication_subjects ps
        JOIN subjects s ON s.id = ps.subject_id
        WHERE ps.publication_id = %s
        ORDER BY s.kind, s.ontology, s.label
        """,
        (pub_id,),
    )
    return db.fetchall()


class TestIngestHal:
    def test_keywords_and_domains(self, db, cache):
        pub = _create_pub(db)
        n = ingest_hal.ingest(
            db,
            publication_id=pub,
            keywords=["machine learning", "AI"],
            topics={"hal_domains": ["info.eea", "sdv.bbm"]},
            cache=cache,
        )
        assert n == 4
        rows = _subjects_of(db, pub)
        assert len(rows) == 4
        kinds = {r["kind"] for r in rows}
        assert kinds == {"free", "concept"}
        ontologies = {r["ontology"] for r in rows if r["kind"] == "concept"}
        assert ontologies == {"hal_domain"}

    def test_empty(self, db, cache):
        pub = _create_pub(db)
        assert (
            ingest_hal.ingest(db, publication_id=pub, keywords=None, topics=None, cache=cache) == 0
        )

    def test_dedup_keywords(self, db, cache):
        pub = _create_pub(db)
        n = ingest_hal.ingest(
            db,
            publication_id=pub,
            keywords=["ML", "ml", "  ML  "],
            topics=None,
            cache=cache,
        )
        assert n == 1


class TestIngestOpenAlex:
    def test_topic_chain_with_parent_links(self, db, cache):
        pub = _create_pub(db)
        n = ingest_openalex.ingest(
            db,
            publication_id=pub,
            keywords=["deep learning"],
            topics=[
                {
                    "domain": "Health Sciences",
                    "field": "Medicine",
                    "subfield": "Cardiology",
                    "topic": "Heart Failure",
                    "score": 0.92,
                }
            ],
            cache=cache,
        )
        assert n == 5  # 1 keyword + 4 niveaux

        rows = _subjects_of(db, pub)
        concepts = [r for r in rows if r["kind"] == "concept"]
        assert len(concepts) == 4
        levels = {r["level"]: r["label"] for r in concepts}
        assert levels == {
            0: "Health Sciences",
            1: "Medicine",
            2: "Cardiology",
            3: "Heart Failure",
        }
        # parent_id chaîné : niveau N parent du niveau N+1.
        by_level = {r["level"]: r for r in concepts}
        assert by_level[0]["parent_id"] is None
        for lvl in (1, 2, 3):
            db.execute(
                "SELECT label, level FROM subjects WHERE id = %s",
                (by_level[lvl]["parent_id"],),
            )
            parent = db.fetchone()
            assert parent["level"] == lvl - 1

    def test_score_only_on_deepest(self, db, cache):
        pub = _create_pub(db)
        ingest_openalex.ingest(
            db,
            publication_id=pub,
            keywords=None,
            topics=[{"domain": "D", "field": "F", "topic": "T", "score": 0.5}],
            cache=cache,
        )
        rows = _subjects_of(db, pub)
        concepts = [r for r in rows if r["kind"] == "concept"]
        scores = {r["level"]: r["score"] for r in concepts}
        # Niveau 3 (topic) porte le score, les autres sont None.
        assert scores[3] == pytest.approx(0.5)
        assert scores[0] is None
        assert scores[1] is None

    def test_partial_hierarchy(self, db, cache):
        pub = _create_pub(db)
        n = ingest_openalex.ingest(
            db,
            publication_id=pub,
            keywords=None,
            topics=[{"domain": "Physical Sciences"}],
            cache=cache,
        )
        assert n == 1

    def test_keywords_marked_en(self, db, cache):
        pub = _create_pub(db)
        ingest_openalex.ingest(
            db, publication_id=pub, keywords=["physics"], topics=None, cache=cache
        )
        db.execute("SELECT language FROM subjects WHERE label = 'physics'")
        assert db.fetchone()["language"] == "en"


class TestIngestWos:
    def test_subjects_and_headings(self, db, cache):
        pub = _create_pub(db)
        n = ingest_wos.ingest(
            db,
            publication_id=pub,
            keywords=["genomics"],
            topics={"subjects": ["Biology"], "headings": ["Life Sciences"]},
            cache=cache,
        )
        assert n == 3
        rows = _subjects_of(db, pub)
        ontos = {r["ontology"] for r in rows if r["kind"] == "concept"}
        assert ontos == {"wos_subject", "wos_heading"}


class TestIngestCrossref:
    def test_keywords_only(self, db, cache):
        pub = _create_pub(db)
        n = ingest_crossref.ingest(
            db,
            publication_id=pub,
            keywords=["Computer Science", "AI"],
            topics={"ignored": True},
            cache=cache,
        )
        assert n == 2
        rows = _subjects_of(db, pub)
        assert all(r["kind"] == "free" for r in rows)


class TestIngestTheses:
    def test_keywords_discipline_rameau(self, db, cache):
        pub = _create_pub(db)
        n = ingest_theses.ingest(
            db,
            publication_id=pub,
            keywords=["intelligence artificielle"],
            topics={"discipline": "Informatique", "rameau": ["Algorithme", "Réseau de neurones"]},
            cache=cache,
        )
        assert n == 4
        rows = _subjects_of(db, pub)
        ontos = {r["ontology"] for r in rows if r["kind"] == "concept"}
        assert ontos == {"theses_discipline", "rameau"}
        db.execute(
            "SELECT DISTINCT language FROM subjects "
            "WHERE id IN (SELECT subject_id FROM publication_subjects WHERE publication_id = %s)",
            (pub,),
        )
        langs = {r["language"] for r in db.fetchall()}
        assert langs == {"fr"}


class TestIngestScanr:
    def test_topics_as_list(self, db, cache):
        pub = _create_pub(db)
        n = ingest_scanr.ingest(
            db,
            publication_id=pub,
            keywords=["écologie"],
            topics=["Sciences de l'environnement"],
            cache=cache,
        )
        assert n == 2

    def test_topics_as_dict_with_domains(self, db, cache):
        pub = _create_pub(db)
        n = ingest_scanr.ingest(
            db,
            publication_id=pub,
            keywords=None,
            topics={"domains": ["Biologie", "Chimie"]},
            cache=cache,
        )
        assert n == 2
        rows = _subjects_of(db, pub)
        assert {r["label"] for r in rows} == {"Biologie", "Chimie"}


class TestRunOrchestrator:
    def test_clears_and_reingests(self, db, queries):
        pub = _create_pub(db)
        _create_source_pub(
            db,
            source="hal",
            source_id="h1",
            publication_id=pub,
            keywords=["initial"],
            topics=None,
        )
        logger = logging.getLogger("test")

        n1 = run(db, queries, logger, sources=["hal"])
        assert n1 == 1
        assert len(_subjects_of(db, pub)) == 1

        # Modifier les keywords et relancer : l'ancien lien doit disparaître.
        db.execute(
            "UPDATE source_publications SET keywords = %s WHERE source_id = 'h1'",
            (["replaced"],),
        )
        n2 = run(db, queries, logger, sources=["hal"])
        assert n2 == 1
        rows = _subjects_of(db, pub)
        assert len(rows) == 1
        assert rows[0]["label"] == "replaced"

    def test_skips_unrelated_sources(self, db, queries):
        pub = _create_pub(db)
        _create_source_pub(db, source="hal", source_id="h1", publication_id=pub, keywords=["x"])
        _create_source_pub(
            db, source="openalex", source_id="oa1", publication_id=pub, keywords=["y"]
        )
        run(db, queries, logging.getLogger("test"), sources=["hal"])
        rows = _subjects_of(db, pub)
        assert len(rows) == 1  # Seul HAL ingéré
        assert rows[0]["label"] == "x"

    def test_ignores_unlinked_source_publications(self, db, queries):
        # source_publication sans publication_id (hors-périmètre) → ignoré.
        db.execute(
            "INSERT INTO source_publications (source, source_id, title, keywords) "
            "VALUES ('hal', 'h-orphan', 'X', %s)",
            (["ghost"],),
        )
        n = run(db, queries, logging.getLogger("test"), sources=["hal"])
        assert n == 0
        db.execute("SELECT count(*) AS n FROM publication_subjects")
        assert db.fetchone()["n"] == 0
