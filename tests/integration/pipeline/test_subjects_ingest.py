"""Lecture des libellés de sujets par source (`extractors`, fonctions pures) et ingestion des sujets en base (`ingestion.run`)."""

import json
import logging

import pytest
from sqlalchemy import text

from pipeline.transformation.publications.store import PublicationStore
from pipeline.transformation.publications.subjects.subject_extractors import (
    hal_labels,
    openalex_labels,
    scanr_labels,
    theses_labels,
    wos_labels,
)
from pipeline.transformation.publications.subjects.subject_ingestion import run
from pipeline.transformation.publications.subjects.subject_store import SubjectStore
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record
from tests.integration.helpers.subjects import insert_subject


class TestExtractors:
    def test_hal_label_from_the_source(self):
        assert hal_labels({"hal_domains": ["phys_FacetSep_Physique [physics]"]}) == ["Physique"]

    def test_hal_all_levels_flat(self):
        topics = {
            "hal_domains": [
                # Une seule entrée, coupée sur deux lignes : le chemin complet des trois niveaux.
                (
                    "sdv.bbm.bm_FacetSep_Sciences du Vivant [q-bio]"
                    "/Biochimie, Biologie Moléculaire/Biologie moléculaire"
                )
            ]
        }
        assert hal_labels(topics) == [
            "Sciences du Vivant",
            "Biochimie, Biologie Moléculaire",
            "Biologie moléculaire",
        ]

    def test_hal_dedups_identical_entries(self):
        entry = "phys_FacetSep_Physique [physics]"
        assert hal_labels({"hal_domains": [entry, entry]}) == ["Physique"]

    def test_hal_generic_leaf_excluded(self):
        assert hal_labels({"hal_domains": ["chim.othe_FacetSep_Chimie/Autre"]}) == ["Chimie"]

    def test_hal_non_dict(self):
        assert hal_labels(None) == []

    def test_openalex_four_levels_flat(self):
        topics = [{"domain": "D", "field": "F", "subfield": "S", "topic": "T", "score": 0.9}]
        assert openalex_labels(topics) == ["D", "F", "S", "T"]

    def test_openalex_partial(self):
        assert openalex_labels([{"domain": "Physical Sciences"}]) == ["Physical Sciences"]

    def test_openalex_non_list(self):
        assert openalex_labels({}) == []

    def test_wos_subjects_and_headings(self):
        topics = {"subjects": ["Biology"], "headings": ["Life Sciences"]}
        assert wos_labels(topics) == ["Biology", "Life Sciences"]

    def test_wos_non_dict(self):
        assert wos_labels([]) == []

    def test_scanr_sudoc_label(self):
        topics = [{"type": "sudoc", "code": "027219046", "label": {"default": "Analgésie"}}]
        assert scanr_labels(topics) == ["Analgésie"]

    def test_scanr_non_list(self):
        assert scanr_labels({"domains": []}) == []

    def test_theses_discipline_and_rameau(self):
        topics = {"discipline": "Informatique", "rameau": ["Algorithme", "Réseau de neurones"]}
        assert theses_labels(topics) == ["Informatique", "Algorithme", "Réseau de neurones"]

    def test_theses_non_dict(self):
        assert theses_labels(None) == []


# Ingestion en base


@pytest.fixture
def queries(sa_sync_conn):
    return SubjectStore(sa_sync_conn)


def _subjects_of(conn, publication_id):
    """Sujets liés à une publication, triés par libellé."""
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
        {"p": publication_id},
    ).all()


def _publications_updated(metrics):
    """Nombre de publications traitées par un passage."""
    return metrics.details["summary"]["publications_updated"]


class TestRunOrchestrator:
    def test_ingests_then_skips_unchanged(self, sa_sync_conn, queries):
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn, publication, topics={"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        )
        logger = logging.getLogger("test")

        # Publication jamais ingérée : ingérée.
        m1 = run(queries, logger)
        assert m1.new == 1
        assert len(_subjects_of(sa_sync_conn, publication)) == 1

        # Publication déjà ingérée (`subjects_ingested_at` renseigné) : ignorée.
        m2 = run(queries, logger)
        assert m2.new == 0
        assert len(_subjects_of(sa_sync_conn, publication)) == 1

    def test_reingests_on_content_change(self, sa_sync_conn, queries):
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn, publication, topics={"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        )
        logger = logging.getLogger("test")
        run(queries, logger)

        # Le topic de l'enregistrement source change. L'enregistrement de la publication recalculée depuis ses sources vide `subjects_ingested_at`.
        sa_sync_conn.execute(
            text("UPDATE source_records SET topics = CAST(:t AS jsonb) WHERE source_id = 'h1'"),
            {"t": json.dumps({"hal_domains": ["phys_FacetSep_Physique [physics]"]})},
        )
        repo = PublicationStore(sa_sync_conn)
        repo.save(repo.find_by_id(publication))

        m2 = run(queries, logger)
        assert m2.new == 1
        rows = _subjects_of(sa_sync_conn, publication)
        assert len(rows) == 1
        assert rows[0].label == "Physique"

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
        insert_source_record(
            sa_sync_conn, publication, topics={"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        )
        logger = logging.getLogger("test")
        run(queries, logger)

        sa_sync_conn.execute(
            text("UPDATE publications SET updated_at = clock_timestamp() WHERE id = :id"),
            {"id": publication},
        )
        assert _publications_updated(run(queries, logger)) == 0

    def test_reingests_all_sources_of_changed_publication(self, sa_sync_conn, queries):
        # L'ingestion lit les sujets de tous les enregistrements sources de la publication.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn, publication, topics={"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        )
        insert_source_record(
            sa_sync_conn,
            publication,
            source="openalex",
            source_id="oa1",
            topics=[{"topic": "Physics"}],
        )
        run(queries, logging.getLogger("test"))
        labels = {r.label for r in _subjects_of(sa_sync_conn, publication)}
        assert labels == {"Informatique", "Physics"}

    def test_same_label_across_sources_merges(self, sa_sync_conn, queries):
        # Un même libellé dans deux sources donne un seul sujet et deux liens, un par source.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn, publication, topics={"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        )
        insert_source_record(
            sa_sync_conn,
            publication,
            source="theses",
            source_id="t1",
            topics={"discipline": "Informatique"},
        )
        run(queries, logging.getLogger("test"))
        subjects = sa_sync_conn.execute(
            text("SELECT id FROM subjects WHERE lower(label) = 'informatique'")
        ).all()
        assert len(subjects) == 1
        rows = _subjects_of(sa_sync_conn, publication)
        assert len(rows) == 2
        assert {r.id for r in rows} == {subjects[0].id}

    def test_rebuild_reingests_all(self, sa_sync_conn, queries):
        # `rebuild=True` ingère aussi une publication non modifiée.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn, publication, topics={"hal_domains": ["info_FacetSep_Informatique [cs]"]}
        )
        logger = logging.getLogger("test")
        run(queries, logger)
        # Sans `rebuild` : rien à faire.
        assert run(queries, logger).new == 0
        # Avec `rebuild` : ingérée de nouveau.
        assert run(queries, logger, rebuild=True).new == 1

    def test_ignores_unlinked_source_records(self, sa_sync_conn, queries):
        # Les sujets d'un enregistrement source sans publication sont ignorés.
        insert_source_record(
            sa_sync_conn, source="openalex", source_id="oa-orphan", topics=[{"topic": "ghosttopic"}]
        )
        run(queries, logging.getLogger("test"))
        n_ghost = sa_sync_conn.execute(
            text("SELECT count(*) FROM subjects WHERE label = 'ghosttopic'")
        ).scalar_one()
        assert n_ghost == 0

    def test_purges_orphan_subjects(self, sa_sync_conn, queries):
        # Un sujet sans lien est supprimé en fin de phase.
        orphan = insert_subject(sa_sync_conn, "orphelin sans lien")
        run(queries, logging.getLogger("test"))
        still = sa_sync_conn.execute(
            text("SELECT 1 FROM subjects WHERE id = :id"), {"id": orphan}
        ).scalar_one_or_none()
        assert still is None
