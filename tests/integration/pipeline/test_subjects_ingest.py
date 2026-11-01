"""Tests d'intégration de la phase `subjects` : liens des publications dérivés des sujets de leurs enregistrements sources, ancêtres compris, et purge des sujets sans lien."""

import logging

import pytest
from sqlalchemy import text

from domain.subjects.subject import (
    Subject,
    SubjectLink,
    SubjectVocabulary,
    theses_discipline_subject,
)
from pipeline.ingestion.common.subjects import SourceRecordSubjectStore
from pipeline.transformation.publications.store import PublicationStore
from pipeline.transformation.publications.subjects.subject_ingestion import run
from pipeline.transformation.publications.subjects.subject_store import SubjectStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record
from tests.integration.helpers.subjects import insert_subject

_INFORMATIQUE = Subject(SubjectVocabulary.HAL_DOMAIN, "info", "Informatique")
_PHYSIQUE = Subject(SubjectVocabulary.HAL_DOMAIN, "phys", "Physique")
_PHYSICAL_SCIENCES = Subject(SubjectVocabulary.OPENALEX, "domains/3", "Physical Sciences")
_PHYSICS_TOPIC = Subject(
    SubjectVocabulary.OPENALEX,
    "T10001",
    "Quantum Mechanics",
    Subject(
        SubjectVocabulary.OPENALEX,
        "subfields/3106",
        "Nuclear and High Energy Physics",
        Subject(SubjectVocabulary.OPENALEX, "fields/31", "Physics", _PHYSICAL_SCIENCES),
    ),
)


@pytest.fixture
def queries(sa_sync_conn):
    return SubjectStore(sa_sync_conn)


def _subjects_of(conn, publication_id):
    """Renvoie les liens d'une publication : libellé du sujet et source, triés."""
    return conn.execute(
        text(
            """
            SELECT s.label, ps.source::text AS source
            FROM publication_subjects ps
            JOIN subjects s ON s.id = ps.subject_id
            WHERE ps.publication_id = :p
            ORDER BY s.level, lower(s.label), ps.source
            """
        ),
        {"p": publication_id},
    ).all()


def _publications_updated(metrics):
    """Renvoie le nombre de publications traitées par un passage."""
    return metrics.details["summary"]["publications_updated"]


class TestRunOrchestrator:
    def test_ingests_then_skips_unchanged(self, sa_sync_conn, queries):
        publication = insert_publication(sa_sync_conn)
        insert_source_record(sa_sync_conn, publication, subjects=[SubjectLink(_INFORMATIQUE)])
        logger = logging.getLogger("test")

        # Publication jamais ingérée : ingérée.
        m1 = run(queries, logger)
        assert m1.new == 1
        assert len(_subjects_of(sa_sync_conn, publication)) == 1

        # Publication déjà ingérée (`subjects_ingested_at` renseigné) : ignorée.
        m2 = run(queries, logger)
        assert m2.new == 0
        assert len(_subjects_of(sa_sync_conn, publication)) == 1

    def test_ancestors_linked_to_the_publication(self, sa_sync_conn, queries):
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn,
            publication,
            source="openalex",
            source_id="oa1",
            subjects=[SubjectLink(_PHYSICS_TOPIC, 0.9)],
        )
        run(queries, logging.getLogger("test"))
        assert [r.label for r in _subjects_of(sa_sync_conn, publication)] == [
            "Physical Sciences",
            "Physics",
            "Nuclear and High Energy Physics",
            "Quantum Mechanics",
        ]

    def test_reingests_on_content_change(self, sa_sync_conn, queries):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, subjects=[SubjectLink(_INFORMATIQUE)]
        )
        logger = logging.getLogger("test")
        run(queries, logger)

        # Les sujets de l'enregistrement source changent. La publication recalculée depuis ses sources vide `subjects_ingested_at`.
        SourceRecordSubjectStore(sa_sync_conn).replace_subjects(
            source_record, [SubjectLink(_PHYSIQUE)]
        )
        repo = PublicationStore(sa_sync_conn)
        publication_entity = repo.find_by_id(publication)
        assert publication_entity is not None
        repo.save(publication_entity)

        m2 = run(queries, logger)
        assert m2.new == 1
        assert [r.label for r in _subjects_of(sa_sync_conn, publication)] == ["Physique"]

    def test_publication_without_subject_not_reselected(self, sa_sync_conn, queries):
        # Une publication sans sujet reçoit aussi sa date d'ingestion : le passage suivant l'ignore.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(sa_sync_conn, publication)
        logger = logging.getLogger("test")

        assert _publications_updated(run(queries, logger)) == 1
        assert _publications_updated(run(queries, logger)) == 0

    def test_other_writes_do_not_reselect(self, sa_sync_conn, queries):
        # Une écriture sans rapport avec les sources (statut open access…) laisse la date d'ingestion en place.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(sa_sync_conn, publication, subjects=[SubjectLink(_INFORMATIQUE)])
        logger = logging.getLogger("test")
        run(queries, logger)

        sa_sync_conn.execute(
            text("UPDATE publications SET updated_at = clock_timestamp() WHERE id = :id"),
            {"id": publication},
        )
        assert _publications_updated(run(queries, logger)) == 0

    def test_one_link_per_source(self, sa_sync_conn, queries):
        """Un même sujet donné par deux sources donne un lien par source ; un même libellé dans deux vocabulaires donne deux sujets."""
        publication = insert_publication(sa_sync_conn)
        rameau = Subject(SubjectVocabulary.RAMEAU, "027940373", "Informatique")
        insert_source_record(
            sa_sync_conn,
            publication,
            source="scanr",
            source_id="sc1",
            subjects=[SubjectLink(rameau)],
        )
        discipline = theses_discipline_subject("Informatique")
        assert discipline is not None
        insert_source_record(
            sa_sync_conn,
            publication,
            source="theses",
            source_id="t1",
            subjects=[SubjectLink(rameau), SubjectLink(discipline)],
        )
        run(queries, logging.getLogger("test"))
        assert (
            sa_sync_conn.execute(
                text("SELECT count(*) FROM subjects WHERE label = 'Informatique'")
            ).scalar_one()
            == 2
        )
        assert [(r.label, r.source) for r in _subjects_of(sa_sync_conn, publication)] == [
            ("Informatique", "scanr"),
            ("Informatique", "theses"),
            ("Informatique", "theses"),
        ]

    def test_rebuild_reingests_all(self, sa_sync_conn, queries):
        # `rebuild=True` ingère aussi une publication non modifiée.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(sa_sync_conn, publication, subjects=[SubjectLink(_INFORMATIQUE)])
        logger = logging.getLogger("test")
        run(queries, logger)
        # Sans `rebuild` : rien à faire.
        assert run(queries, logger).new == 0
        # Avec `rebuild` : ingérée de nouveau.
        assert run(queries, logger, rebuild=True).new == 1

    def test_purges_orphan_subjects_and_keeps_ancestors(self, sa_sync_conn, queries):
        """Un sujet sans lien est supprimé en fin de phase ; l'ancêtre d'un sujet lié reste."""
        orphan = insert_subject(sa_sync_conn, "orphelin sans lien")
        insert_source_record(
            sa_sync_conn, source="openalex", source_id="oa1", subjects=[SubjectLink(_PHYSICS_TOPIC)]
        )
        run(queries, logging.getLogger("test"))
        labels = set(sa_sync_conn.execute(text("SELECT label FROM subjects")).scalars())
        assert "orphelin sans lien" not in labels
        assert {"Physical Sciences", "Quantum Mechanics"} <= labels
        assert orphan not in set(sa_sync_conn.execute(text("SELECT id FROM subjects")).scalars())
