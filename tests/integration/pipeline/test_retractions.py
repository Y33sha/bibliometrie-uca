"""Indicateur « Rétracté » des publications, écrit par la tâche `retracted` de la phase `relations`."""

import logging

from sqlalchemy import text

from pipeline.transformation.publications.retractions import mark_retracted
from tests.integration.helpers.publications import insert_publication, insert_publication_relation
from tests.integration.helpers.sources import insert_source_record


def _retracted(conn, *ids) -> list[bool]:
    rows = conn.execute(
        text("SELECT id, is_retracted FROM publications WHERE id = ANY(:ids)"), {"ids": list(ids)}
    ).all()
    flags = dict(tuple(r) for r in rows)
    return [flags[i] for i in ids]


def _crossref(conn, publication_id, doi, **source_extras) -> None:
    insert_source_record(
        conn,
        publication_id,
        source="crossref",
        source_id=doi,
        title="t",
        doi=doi,
        source_extras=source_extras,
    )


def _run(conn) -> None:
    mark_retracted(conn, logging.getLogger("test"))


class TestMarkRetracted:
    def test_article_vise_par_une_relation_et_avis_exclu(self, sa_sync_conn):
        """OpenAlex marque aussi l'avis : l'avis, sujet de `is_retraction_of`, reste non rétracté."""
        article = insert_publication(sa_sync_conn, doc_type="article")
        notice = insert_publication(sa_sync_conn, doc_type="retraction")
        insert_publication_relation(
            sa_sync_conn,
            notice,
            relation_type="is_retraction_of",
            source="crossref",
            target_publication_id=article,
        )
        insert_source_record(
            sa_sync_conn, notice, source="openalex", source_id="W-avis", is_retracted=True
        )
        _run(sa_sync_conn)
        assert _retracted(sa_sync_conn, article, notice) == [True, False]

    def test_retractation_sur_place(self, sa_sync_conn):
        """Cas réel : Elsevier déclare la rétractation vers le DOI de l'article lui-même (10.1016/j.indmarman.2022.05.009)."""
        article = insert_publication(sa_sync_conn, doc_type="article")
        _crossref(
            sa_sync_conn,
            article,
            "10.1/sur-place",
            update_to=[{"doi": "10.1/sur-place", "type": "retraction", "source": "publisher"}],
        )
        _run(sa_sync_conn)
        assert _retracted(sa_sync_conn, article) == [True]

    def test_doublon_retire(self, sa_sync_conn):
        """Cas réel : la version française retirée, doublon accidentel, déclare un retrait vers l'article (10.1016/j.rhum.2022.12.007)."""
        original = insert_publication(sa_sync_conn, doc_type="article", doi="10.1/original")
        duplicate = insert_publication(sa_sync_conn, doc_type="article")
        _crossref(
            sa_sync_conn,
            duplicate,
            "10.1/doublon",
            update_to=[{"doi": "10.1/original", "type": "withdrawal", "source": "publisher"}],
        )
        _crossref(
            sa_sync_conn,
            original,
            "10.1/original",
            updated_by=[{"doi": "10.1/doublon", "type": "withdrawal", "source": "publisher"}],
        )
        _run(sa_sync_conn)
        assert _retracted(sa_sync_conn, original, duplicate) == [False, True]

    def test_publication_sans_signal_demarquee(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, doc_type="article")
        sa_sync_conn.execute(
            text("UPDATE publications SET is_retracted = true WHERE id = :id"), {"id": publication}
        )
        _run(sa_sync_conn)
        assert _retracted(sa_sync_conn, publication) == [False]
