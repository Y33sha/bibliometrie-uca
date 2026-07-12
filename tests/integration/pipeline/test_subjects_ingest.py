"""Tests d'intégration des ingestors `application/pipeline/subjects/*`
et de l'orchestrateur d'ingestion."""

import json
import logging

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.pipeline.subjects import (
    ingest_hal,
    ingest_openalex,
    ingest_scanr,
    ingest_theses,
    ingest_wos,
)
from application.pipeline.subjects._common import SubjectCache
from application.pipeline.subjects.ingestion import run
from infrastructure.queries.subjects import PgSubjectsQueries


@pytest.fixture
def cache():
    return SubjectCache(PgSubjectsQueries())


@pytest.fixture
def queries():
    return PgSubjectsQueries()


def _create_pub(conn, title="X"):
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, doc_type) "
            "VALUES (:t, 2024, 'article') RETURNING id"
        ),
        {"t": title},
    ).scalar_one()


_CREATE_SOURCE_PUB_SQL = text(
    """
    INSERT INTO source_publications (source, source_id, title, publication_id, topics)
    VALUES (:source, :source_id, 'X', :publication_id, :topics) RETURNING id
    """
).bindparams(bindparam("topics", type_=JSONB))


def _create_source_pub(conn, *, source, source_id, publication_id, topics=None):
    return conn.execute(
        _CREATE_SOURCE_PUB_SQL,
        {
            "source": source,
            "source_id": source_id,
            "publication_id": publication_id,
            "topics": topics,
        },
    ).scalar_one()


def _subjects_of(conn, pub_id):
    """Sujets liés à une publication, triés par label."""
    return conn.execute(
        text(
            """
            SELECT s.id, s.label, s.language
            FROM publication_subjects ps
            JOIN subjects s ON s.id = ps.subject_id
            WHERE ps.publication_id = :p
            ORDER BY lower(s.label)
            """
        ),
        {"p": pub_id},
    ).all()


class TestIngestHal:
    def test_domains(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics={"hal_domains": ["info.eea", "sdv.bbm"]},
            cache=cache,
        )
        assert n == 2
        assert len(_subjects_of(sa_sync_conn, pub)) == 2

    def test_empty(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        assert ingest_hal.ingest(sa_sync_conn, publication_id=pub, topics=None, cache=cache) == 0

    def test_strips_level_prefix_and_derives_label(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics={"hal_domains": ["0.phys", "1.phys.hexp"]},
            cache=cache,
        )
        assert n == 2
        # Libellé feuille dérivé du référentiel CCSD.
        assert "Physique" in {r.label for r in _subjects_of(sa_sync_conn, pub)}

    def test_dedup_same_code_at_multiple_levels(self, sa_sync_conn, cache):
        # '0.phys' → 'phys' et 'phys' → 'phys' = même code, une seule entrée.
        pub = _create_pub(sa_sync_conn)
        n = ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics={"hal_domains": ["0.phys", "phys"]},
            cache=cache,
        )
        assert n == 1


class TestIngestOpenAlex:
    def test_four_levels_flat(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_openalex.ingest(
            sa_sync_conn,
            publication_id=pub,
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
        assert n == 4  # les 4 niveaux, à plat
        labels = {r.label for r in _subjects_of(sa_sync_conn, pub)}
        assert labels == {"Health Sciences", "Medicine", "Cardiology", "Heart Failure"}

    def test_partial_hierarchy(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_openalex.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics=[{"domain": "Physical Sciences"}],
            cache=cache,
        )
        assert n == 1

    def test_language_en(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        ingest_openalex.ingest(
            sa_sync_conn, publication_id=pub, topics=[{"topic": "Physics"}], cache=cache
        )
        lang = sa_sync_conn.execute(
            text("SELECT language FROM subjects WHERE label = 'Physics'")
        ).scalar_one()
        assert lang == "en"


class TestIngestWos:
    def test_subjects_and_headings(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_wos.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics={"subjects": ["Biology"], "headings": ["Life Sciences"]},
            cache=cache,
        )
        assert n == 2
        assert {r.label for r in _subjects_of(sa_sync_conn, pub)} == {"Biology", "Life Sciences"}


class TestIngestTheses:
    def test_discipline_and_rameau(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_theses.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics={"discipline": "Informatique", "rameau": ["Algorithme", "Réseau de neurones"]},
            cache=cache,
        )
        assert n == 3
        assert {r.label for r in _subjects_of(sa_sync_conn, pub)} == {
            "Informatique",
            "Algorithme",
            "Réseau de neurones",
        }


class TestIngestScanr:
    def test_topics_as_list(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_scanr.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics=["Sciences de l'environnement"],
            cache=cache,
        )
        assert n == 1

    def test_topics_as_dict_with_domains(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_scanr.ingest(
            sa_sync_conn,
            publication_id=pub,
            topics={"domains": ["Biologie", "Chimie"]},
            cache=cache,
        )
        assert n == 2
        assert {r.label for r in _subjects_of(sa_sync_conn, pub)} == {"Biologie", "Chimie"}


class TestFusionAcrossSources:
    def test_same_label_merges_to_one_subject(self, sa_sync_conn, cache):
        # Un même label depuis deux sources → un seul subject, deux liens (un par source).
        pub = _create_pub(sa_sync_conn)
        ingest_hal.ingest(
            sa_sync_conn, publication_id=pub, topics={"hal_domains": ["info"]}, cache=cache
        )
        ingest_theses.ingest(
            sa_sync_conn, publication_id=pub, topics={"discipline": "Informatique"}, cache=cache
        )
        subjects = sa_sync_conn.execute(
            text("SELECT id FROM subjects WHERE lower(label) = 'informatique'")
        ).all()
        assert len(subjects) == 1
        rows = _subjects_of(sa_sync_conn, pub)
        assert len(rows) == 2
        assert {r.id for r in rows} == {subjects[0].id}


class TestRunOrchestrator:
    def test_ingests_then_skips_unchanged(self, sa_sync_conn, queries):
        pub = _create_pub(sa_sync_conn)
        _create_source_pub(
            sa_sync_conn,
            source="hal",
            source_id="h1",
            publication_id=pub,
            topics={"hal_domains": ["info"]},
        )
        logger = logging.getLogger("test")

        # Jamais ingérée → ingérée.
        m1 = run(sa_sync_conn, queries, logger)
        assert m1.new == 1
        assert len(_subjects_of(sa_sync_conn, pub)) == 1

        # Sans changement : updated_at <= created_at des liens → ignorée.
        m2 = run(sa_sync_conn, queries, logger)
        assert m2.new == 0
        assert len(_subjects_of(sa_sync_conn, pub)) == 1

    def test_reingests_on_content_change(self, sa_sync_conn, queries):
        pub = _create_pub(sa_sync_conn)
        _create_source_pub(
            sa_sync_conn,
            source="hal",
            source_id="h1",
            publication_id=pub,
            topics={"hal_domains": ["info"]},
        )
        logger = logging.getLogger("test")
        run(sa_sync_conn, queries, logger)

        # Changement de contenu : nouveau topic + bump de publications.updated_at (ce
        # que fait refresh_from_sources en réel quand une source change).
        sa_sync_conn.execute(
            text(
                "UPDATE source_publications SET topics = CAST(:t AS jsonb) WHERE source_id = 'h1'"
            ),
            {"t": json.dumps({"hal_domains": ["phys"]})},
        )
        sa_sync_conn.execute(
            text("UPDATE publications SET updated_at = clock_timestamp() WHERE id = :id"),
            {"id": pub},
        )
        m2 = run(sa_sync_conn, queries, logger)
        assert m2.new == 1
        rows = _subjects_of(sa_sync_conn, pub)
        assert len(rows) == 1
        assert rows[0].label == "Physique"

    def test_reingests_all_sources_of_changed_pub(self, sa_sync_conn, queries):
        # Publication-centré : toutes les sources d'une pub changée sont ré-ingérées.
        pub = _create_pub(sa_sync_conn)
        _create_source_pub(
            sa_sync_conn,
            source="hal",
            source_id="h1",
            publication_id=pub,
            topics={"hal_domains": ["info"]},
        )
        _create_source_pub(
            sa_sync_conn,
            source="openalex",
            source_id="oa1",
            publication_id=pub,
            topics=[{"topic": "Physics"}],
        )
        run(sa_sync_conn, queries, logging.getLogger("test"))
        labels = {r.label for r in _subjects_of(sa_sync_conn, pub)}
        assert labels == {"Informatique", "Physics"}

    def test_multi_source_pub_same_source_keeps_both(self, sa_sync_conn, queries):
        # Deux source_publications de la MÊME source sur une pub (cas ~7%) : le clear
        # étant par publication, les deux jumeaux sont ré-ingérés ensemble.
        pub = _create_pub(sa_sync_conn)
        _create_source_pub(
            sa_sync_conn,
            source="hal",
            source_id="h1",
            publication_id=pub,
            topics={"hal_domains": ["info"]},
        )
        _create_source_pub(
            sa_sync_conn,
            source="hal",
            source_id="h2",
            publication_id=pub,
            topics={"hal_domains": ["phys"]},
        )
        run(sa_sync_conn, queries, logging.getLogger("test"))
        labels = {r.label for r in _subjects_of(sa_sync_conn, pub)}
        assert labels == {"Informatique", "Physique"}

    def test_ignores_unlinked_source_publications(self, sa_sync_conn, queries):
        # source_pub orphelin (publication_id NULL) : aucune publication ne le
        # référence → jamais sélectionné, son concept n'est pas ingéré.
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, topics) "
                "VALUES ('openalex', 'oa-orphan', 'X', CAST(:t AS jsonb))"
            ),
            {"t": json.dumps([{"topic": "ghosttopic"}])},
        )
        run(sa_sync_conn, queries, logging.getLogger("test"))
        n_ghost = sa_sync_conn.execute(
            text("SELECT count(*) FROM subjects WHERE label = 'ghosttopic'")
        ).scalar_one()
        assert n_ghost == 0

    def test_purges_orphan_subjects(self, sa_sync_conn, queries):
        # Un sujet sans aucun lien est purgé en fin de phase.
        orphan = sa_sync_conn.execute(
            text("INSERT INTO subjects (label) VALUES ('orphelin sans lien') RETURNING id")
        ).scalar_one()
        run(sa_sync_conn, queries, logging.getLogger("test"))
        still = sa_sync_conn.execute(
            text("SELECT 1 FROM subjects WHERE id = :id"), {"id": orphan}
        ).scalar_one_or_none()
        assert still is None
