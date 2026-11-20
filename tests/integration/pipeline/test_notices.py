"""Phase `relations`, tâche `link_notices` : relations des publications avec leurs errata et leurs avis, qui sont hors des publications."""

import logging

from sqlalchemy import text

from pipeline.transformation.publications.relations import notices
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record

PARENT_TITLE = "measurement of differential cross sections in proton collisions"
"""Titre au-dessus de la garde de longueur (plus de 30 caractères)."""


def _publication(conn, *, doi, doc_type="article", title=PARENT_TITLE, year=2024) -> int:
    return insert_publication(
        conn, title, title_normalized=title, doc_type=doc_type, doi=doi, publication_year=year
    )


def _notice(
    conn,
    doi,
    *,
    source="crossref",
    doc_type="erratum",
    title="t",
    year=2024,
    is_matchable=True,
    **extras,
):
    """Insère l'enregistrement source d'un avis, sans publication."""
    insert_source_record(
        conn,
        None,
        source=source,
        source_id=doi or f"{source}:{title}",
        title=title,
        title_normalized=title.lower(),
        doi=doi,
        doc_type=doc_type,
        publication_year=year,
        source_extras=extras or None,
        is_matchable=is_matchable,
    )


def _edges(conn) -> list[tuple[object, ...]]:
    notices.rebuild(conn, logging.getLogger("test"))
    return [
        tuple(r)
        for r in conn.execute(
            text(
                "SELECT from_publication_id, relation_type::text, target_doi, source "
                "FROM publication_relations ORDER BY from_publication_id, target_doi"
            )
        )
    ]


class TestDeclaredUpdates:
    def test_avis_vers_l_article_en_base(self, sa_sync_conn):
        """L'avis déclare l'article en base, un article absent de la base et son propre DOI (rétractation sur place) : seul l'article en base reçoit la relation."""
        article = _publication(sa_sync_conn, doi="10.1/a")
        _notice(
            sa_sync_conn,
            "10.1/n",
            doc_type="retraction",
            update_to=[
                {"doi": "10.1/a", "type": "retraction", "source": "publisher"},
                {"doi": "10.1/absent", "type": "retraction", "source": "retraction-watch"},
                {"doi": "10.1/n", "type": "retraction", "source": "publisher"},
            ],
        )
        assert _edges(sa_sync_conn) == [(article, "has_retraction", "10.1/n", "crossref")]

    def test_avis_de_retractation_declare_comme_erratum(self, sa_sync_conn):
        """Cas réel (Elsevier, 10.1016/j.joca.2026.08.003) : l'avis et l'article déclarent un erratum ; le type de l'avis donne une rétractation."""
        article = _publication(sa_sync_conn, doi="10.1/a", doc_type="poster")
        insert_source_record(
            sa_sync_conn,
            article,
            source="crossref",
            source_id="10.1/a",
            title="t",
            doi="10.1/a",
            source_extras={
                "updated_by": [{"doi": "10.1/n", "type": "erratum", "source": "publisher"}]
            },
        )
        _notice(
            sa_sync_conn,
            "10.1/n",
            doc_type="retraction",
            update_to=[{"doi": "10.1/a", "type": "erratum", "source": "publisher"}],
        )
        assert _edges(sa_sync_conn) == [(article, "has_retraction", "10.1/n", "crossref")]

    def test_erratum_absent_de_la_base(self, sa_sync_conn):
        """L'article déclare un erratum sans enregistrement source : le type déclaré reste."""
        article = _publication(sa_sync_conn, doi="10.1/a")
        insert_source_record(
            sa_sync_conn,
            article,
            source="crossref",
            source_id="10.1/a",
            title="t",
            doi="10.1/a",
            source_extras={
                "updated_by": [{"doi": "10.1/e", "type": "correction", "source": "publisher"}]
            },
        )
        assert _edges(sa_sync_conn) == [(article, "has_correction", "10.1/e", "crossref")]


class TestWosReference:
    _TITLE = "Measurement of differential cross sections in proton collisions (vol 72, 2100, 2012)"

    def test_article_designe_par_la_reference(self, sa_sync_conn):
        """L'article et l'erratum sont séparés de huit ans : l'année vient de la référence. Le jeu de données de même titre n'empêche pas le rattachement."""
        article = _publication(sa_sync_conn, doi="10.1/a", year=2012)
        _publication(sa_sync_conn, doi="10.1/data", doc_type="dataset", year=2012)
        _notice(sa_sync_conn, "10.1/e", source="wos", title=self._TITLE, year=2020)
        assert _edges(sa_sync_conn) == [(article, "has_correction", "10.1/e", "title_match")]

    def test_article_hors_de_l_annee_de_la_reference(self, sa_sync_conn):
        _publication(sa_sync_conn, doi="10.1/a", year=2015)
        _notice(sa_sync_conn, "10.1/e", source="wos", title=self._TITLE, year=2020)
        assert _edges(sa_sync_conn) == []


class TestTitleMatch:
    _TITLE = f"erratum to {PARENT_TITLE}"

    def test_seul_candidat_substantiel(self, sa_sync_conn):
        """Le preprint de même titre, autre forme de l'article, n'empêche pas le rattachement."""
        article = _publication(sa_sync_conn, doi=None)
        _publication(sa_sync_conn, doi="10.1/p", doc_type="preprint")
        _notice(sa_sync_conn, "10.1/e", source="hal", title=self._TITLE)
        assert _edges(sa_sync_conn) == [(article, "has_correction", "10.1/e", "title_match")]

    def test_deux_articles_de_meme_titre(self, sa_sync_conn):
        _publication(sa_sync_conn, doi="10.1/a1")
        _publication(sa_sync_conn, doi="10.1/a2")
        _notice(sa_sync_conn, "10.1/e", source="hal", title=self._TITLE)
        assert _edges(sa_sync_conn) == []

    def test_article_hors_de_la_fenetre_d_annees(self, sa_sync_conn):
        _publication(sa_sync_conn, doi="10.1/a", year=2020)
        _notice(sa_sync_conn, "10.1/e", source="hal", title=self._TITLE, year=2024)
        assert _edges(sa_sync_conn) == []

    def test_titre_court(self, sa_sync_conn):
        _publication(sa_sync_conn, doi="10.1/a", title="short title")
        _notice(sa_sync_conn, "10.1/e", source="hal", title="erratum to short title")
        assert _edges(sa_sync_conn) == []

    def test_avis_sans_doi(self, sa_sync_conn):
        """Sans DOI, l'avis ne peut être la cible d'une relation."""
        _publication(sa_sync_conn, doi="10.1/a")
        _notice(sa_sync_conn, None, source="hal", title=self._TITLE)
        assert _edges(sa_sync_conn) == []

    def test_avis_ecarte_de_la_reconciliation(self, sa_sync_conn):
        """Cas réel : le doublon retiré d'un corrigendum (10.1016/j.scitotenv.2024.172613) reste sans relation."""
        _publication(sa_sync_conn, doi="10.1/a")
        _notice(sa_sync_conn, "10.1/e", title=self._TITLE, is_matchable=False)
        assert _edges(sa_sync_conn) == []
