"""Tests d'intégration des ingestors `application/pipeline/subjects/*`
et de l'orchestrateur `run.py`."""

import logging

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

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
    INSERT INTO source_publications (source, source_id, title, publication_id, keywords, topics)
    VALUES (:source, :source_id, 'X', :publication_id, :keywords, :topics) RETURNING id
    """
).bindparams(bindparam("topics", type_=JSONB))


def _create_source_pub(conn, *, source, source_id, publication_id, keywords=None, topics=None):
    return conn.execute(
        _CREATE_SOURCE_PUB_SQL,
        {
            "source": source,
            "source_id": source_id,
            "publication_id": publication_id,
            "keywords": keywords,
            "topics": topics,
        },
    ).scalar_one()


def _subjects_of(conn, pub_id):
    """Retourne les sujets liés à une publication, triés par label."""
    return conn.execute(
        text(
            """
            SELECT s.id, s.label, s.language, s.ontologies, ps.score
            FROM publication_subjects ps
            JOIN subjects s ON s.id = ps.subject_id
            WHERE ps.publication_id = :p
            ORDER BY lower(s.label)
            """
        ),
        {"p": pub_id},
    ).all()


def _is_free(row) -> bool:
    return row.ontologies == {}


def _codes_in(row, ontology):
    """Retourne la liste des codes pour une ontologie donnée du sujet."""
    entry = row.ontologies.get(ontology)
    return entry.get("codes", []) if entry else []


def _level_in(row, ontology):
    """Retourne le level pour une ontologie donnée du sujet, ou None."""
    entry = row.ontologies.get(ontology)
    return entry.get("level") if entry else None


def _parent_in(row, ontology):
    entry = row.ontologies.get(ontology)
    return entry.get("parent") if entry else None


class TestIngestHal:
    def test_keywords_and_domains(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=["machine learning", "AI"],
            topics={"hal_domains": ["info.eea", "sdv.bbm"]},
            cache=cache,
        )
        assert n == 4
        rows = _subjects_of(sa_sync_conn, pub)
        assert len(rows) == 4
        # 2 libres (keywords) + 2 concepts hal_domain.
        free_count = sum(1 for r in rows if _is_free(r))
        concept_count = sum(1 for r in rows if not _is_free(r))
        assert free_count == 2
        assert concept_count == 2
        for r in rows:
            if not _is_free(r):
                assert "hal_domain" in r.ontologies

    def test_empty(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        assert (
            ingest_hal.ingest(
                sa_sync_conn, publication_id=pub, keywords=None, topics=None, cache=cache
            )
            == 0
        )

    def test_dedup_keywords(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=["ML", "ml", "  ML  "],
            topics=None,
            cache=cache,
        )
        assert n == 1

    def test_strips_level_prefix_from_hal_domains(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics={"hal_domains": ["0.phys", "1.phys.hexp"]},
            cache=cache,
        )
        assert n == 2
        rows = _subjects_of(sa_sync_conn, pub)
        codes = []
        for r in rows:
            codes.extend(_codes_in(r, "hal_domain"))
        assert set(codes) == {"phys", "phys.hexp"}
        # Libellés depuis le référentiel HAL_DOMAINS.
        assert "Physique" in {r.label for r in rows}

    def test_dedup_same_code_at_multiple_levels(self, sa_sync_conn, cache):
        # '0.phys' → 'phys' et 'phys' → 'phys' = même code, une seule entrée.
        pub = _create_pub(sa_sync_conn)
        n = ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics={"hal_domains": ["0.phys", "phys"]},
            cache=cache,
        )
        assert n == 1


class TestIngestOpenAlex:
    def test_topic_chain_with_parent_links(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_openalex.ingest(
            sa_sync_conn,
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
        assert n == 5  # 1 keyword libre + 4 niveaux concept
        rows = _subjects_of(sa_sync_conn, pub)
        concepts = [r for r in rows if not _is_free(r)]
        assert len(concepts) == 4
        # Le level et le parent sont stockés dans ontologies.openalex_topic.
        levels = {_level_in(r, "openalex_topic"): r.label for r in concepts}
        assert levels == {
            0: "Health Sciences",
            1: "Medicine",
            2: "Cardiology",
            3: "Heart Failure",
        }
        # Chaîne parent : level N a comme parent le label de level N-1.
        parents = {
            _level_in(r, "openalex_topic"): _parent_in(r, "openalex_topic") for r in concepts
        }
        assert parents[0] is None
        assert parents[1] == "Health Sciences"
        assert parents[2] == "Medicine"
        assert parents[3] == "Cardiology"

    def test_score_only_on_deepest(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        ingest_openalex.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics=[{"domain": "D", "field": "F", "topic": "T", "score": 0.5}],
            cache=cache,
        )
        rows = _subjects_of(sa_sync_conn, pub)
        scores = {_level_in(r, "openalex_topic"): r.score for r in rows}
        assert scores[3] == pytest.approx(0.5)
        assert scores[0] is None
        assert scores[1] is None

    def test_partial_hierarchy(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_openalex.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics=[{"domain": "Physical Sciences"}],
            cache=cache,
        )
        assert n == 1

    def test_keywords_no_language(self, sa_sync_conn, cache):
        # Les libres sont stockés sans langue pour permettre la dédup
        # inter-sources.
        pub = _create_pub(sa_sync_conn)
        ingest_openalex.ingest(
            sa_sync_conn, publication_id=pub, keywords=["physics"], topics=None, cache=cache
        )
        lang = sa_sync_conn.execute(
            text("SELECT language FROM subjects WHERE label = 'physics'")
        ).scalar_one()
        assert lang is None


class TestIngestWos:
    def test_subjects_and_headings(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_wos.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=["genomics"],
            topics={"subjects": ["Biology"], "headings": ["Life Sciences"]},
            cache=cache,
        )
        assert n == 3
        rows = _subjects_of(sa_sync_conn, pub)
        all_keys: set[str] = set()
        for r in rows:
            all_keys.update(r.ontologies.keys())
        assert {"wos_subject", "wos_heading"}.issubset(all_keys)


class TestIngestCrossref:
    def test_keywords_only(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_crossref.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=["Computer Science", "AI"],
            topics={"ignored": True},
            cache=cache,
        )
        assert n == 2
        rows = _subjects_of(sa_sync_conn, pub)
        assert all(_is_free(r) for r in rows)


class TestIngestTheses:
    def test_keywords_discipline_rameau(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_theses.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=["intelligence artificielle"],
            topics={"discipline": "Informatique", "rameau": ["Algorithme", "Réseau de neurones"]},
            cache=cache,
        )
        assert n == 4
        rows = _subjects_of(sa_sync_conn, pub)
        all_keys: set[str] = set()
        for r in rows:
            all_keys.update(r.ontologies.keys())
        assert {"theses_discipline", "rameau"}.issubset(all_keys)


class TestIngestScanr:
    def test_topics_as_list(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_scanr.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=["écologie"],
            topics=["Sciences de l'environnement"],
            cache=cache,
        )
        assert n == 2

    def test_topics_as_dict_with_domains(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        n = ingest_scanr.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics={"domains": ["Biologie", "Chimie"]},
            cache=cache,
        )
        assert n == 2
        rows = _subjects_of(sa_sync_conn, pub)
        assert {r.label for r in rows} == {"Biologie", "Chimie"}


class TestFusionAcrossSources:
    """Test du cœur de la refonte B : un même label fusionne les ontologies
    de plusieurs sources en un seul subject."""

    def test_same_label_across_ontologies_merges(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        ingest_hal.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics={"hal_domains": ["info"]},
            cache=cache,
        )
        ingest_theses.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics={"discipline": "Informatique"},
            cache=cache,
        )
        # Un seul subject côté table `subjects` (fusion par label).
        subjects = sa_sync_conn.execute(
            text("SELECT id, ontologies FROM subjects WHERE lower(label) = 'informatique'")
        ).all()
        assert len(subjects) == 1
        onto = subjects[0].ontologies
        assert "hal_domain" in onto
        assert "theses_discipline" in onto
        # Mais deux liens publication_subjects (un par source).
        rows = _subjects_of(sa_sync_conn, pub)
        assert len(rows) == 2
        assert {r.id for r in rows} == {subjects[0].id}

    def test_concept_and_free_merge(self, sa_sync_conn, cache):
        pub = _create_pub(sa_sync_conn)
        # CrossRef fournit un libre "Biology".
        ingest_crossref.ingest(
            sa_sync_conn, publication_id=pub, keywords=["Biology"], topics=None, cache=cache
        )
        # WoS fournit le même comme catégorie.
        ingest_wos.ingest(
            sa_sync_conn,
            publication_id=pub,
            keywords=None,
            topics={"subjects": ["Biology"]},
            cache=cache,
        )
        subjects = sa_sync_conn.execute(
            text("SELECT id, ontologies FROM subjects WHERE lower(label) = 'biology'")
        ).all()
        assert len(subjects) == 1
        # Le subject canonique gagne l'ontologie WoS (CrossRef ne portait rien).
        onto = subjects[0].ontologies
        assert set(onto.keys()) == {"wos_subject"}
        assert onto["wos_subject"]["codes"] == ["biology"]


class TestRunOrchestrator:
    def test_ingests_then_skips_unchanged(self, sa_sync_conn, queries):
        pub = _create_pub(sa_sync_conn)
        _create_source_pub(
            sa_sync_conn, source="hal", source_id="h1", publication_id=pub, keywords=["initial"]
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
            sa_sync_conn, source="hal", source_id="h1", publication_id=pub, keywords=["initial"]
        )
        logger = logging.getLogger("test")
        run(sa_sync_conn, queries, logger)

        # Changement de contenu : keywords + bump de publications.updated_at (ce
        # que fait refresh_from_sources en réel quand une source change).
        sa_sync_conn.execute(
            text("UPDATE source_publications SET keywords = :kw WHERE source_id = 'h1'"),
            {"kw": ["replaced"]},
        )
        sa_sync_conn.execute(
            text("UPDATE publications SET updated_at = clock_timestamp() WHERE id = :id"),
            {"id": pub},
        )
        m2 = run(sa_sync_conn, queries, logger)
        assert m2.new == 1
        rows = _subjects_of(sa_sync_conn, pub)
        assert len(rows) == 1
        assert rows[0].label == "replaced"

    def test_reingests_all_sources_of_changed_pub(self, sa_sync_conn, queries):
        # Publication-centré : toutes les sources d'une pub changée sont ré-ingérées.
        pub = _create_pub(sa_sync_conn)
        _create_source_pub(
            sa_sync_conn, source="hal", source_id="h1", publication_id=pub, keywords=["x"]
        )
        _create_source_pub(
            sa_sync_conn, source="openalex", source_id="oa1", publication_id=pub, keywords=["y"]
        )
        run(sa_sync_conn, queries, logging.getLogger("test"))
        labels = {r.label for r in _subjects_of(sa_sync_conn, pub)}
        assert labels == {"x", "y"}

    def test_multi_source_pub_same_source_keeps_both(self, sa_sync_conn, queries):
        # Deux source_publications de la MÊME source sur une pub (cas ~7%) : le
        # clear étant par publication, les deux jumeaux sont ré-ingérés ensemble
        # — aucun lien perdu.
        pub = _create_pub(sa_sync_conn)
        _create_source_pub(
            sa_sync_conn, source="hal", source_id="h1", publication_id=pub, keywords=["alpha"]
        )
        _create_source_pub(
            sa_sync_conn, source="hal", source_id="h2", publication_id=pub, keywords=["beta"]
        )
        run(sa_sync_conn, queries, logging.getLogger("test"))
        labels = {r.label for r in _subjects_of(sa_sync_conn, pub)}
        assert labels == {"alpha", "beta"}

    def test_ignores_unlinked_source_publications(self, sa_sync_conn, queries):
        # source_pub orphelin (publication_id NULL) : aucune publication ne le
        # référence → jamais sélectionné, son keyword n'est pas ingéré.
        sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, keywords) "
                "VALUES ('hal', 'h-orphan', 'X', :kw)"
            ),
            {"kw": ["ghost"]},
        )
        run(sa_sync_conn, queries, logging.getLogger("test"))
        n_ghost = sa_sync_conn.execute(
            text("SELECT count(*) FROM subjects WHERE label = 'ghost'")
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
