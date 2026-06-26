"""Intégration : rapprochement erratum → œuvre corrigée par le titre (signal #3).

Valide sur vraie base le SQL `fetch_erratum_title_matches` et sa garde d'ambiguïté : suffixe de
titre, fenêtre d'année, garde de longueur, et surtout l'abstention dès que plus d'un parent
« substantiel » (hors preprint / dataset) porte le même titre.
"""

from infrastructure.queries.pipeline.relations import fetch_erratum_title_matches
from infrastructure.repositories import publication_repository

# Titre de parent assez long pour franchir la garde de longueur (> 30 caractères).
PARENT_TITLE = "measurement of differential cross sections in proton collisions"


def _pub(conn, *, doc_type, title_normalized, doi, pub_year=2024) -> int:
    return publication_repository(conn).create(
        title=title_normalized,
        title_normalized=title_normalized,
        doc_type=doc_type,
        pub_year=pub_year,
        doi=doi,
        oa_status="unknown",
        journal_id=None,
        container_title=None,
        language=None,
    )


class TestFetchErratumTitleMatches:
    def test_unique_substantive_parent_matched(self, sa_sync_conn):
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/parent")
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.erratum_id, m.parent_doi) for m in matches] == [(err, "10.1/parent")]

    def test_two_substantive_same_title_blocked(self, sa_sync_conn):
        # Deux articles distincts au même titre = collision → abstention (garde de Laura).
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/p1")
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/p2")
        _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        assert fetch_erratum_title_matches(sa_sync_conn) == []

    def test_preprint_does_not_block_and_article_chosen(self, sa_sync_conn):
        # Le preprint partage le titre mais ne compte pas comme parent substantiel : on relie l'article.
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/article")
        _pub(sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/preprint")
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.erratum_id, m.parent_doi) for m in matches] == [(err, "10.1/article")]

    def test_parent_outside_year_window_not_matched(self, sa_sync_conn):
        _pub(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/parent",
            pub_year=2020,
        )
        _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
            pub_year=2024,
        )
        assert fetch_erratum_title_matches(sa_sync_conn) == []

    def test_short_title_not_matched(self, sa_sync_conn):
        short = "short title"  # <= 30 caractères → sous la garde de longueur
        _pub(sa_sync_conn, doc_type="article", title_normalized=short, doi="10.1/parent")
        _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {short}",
            doi="10.1/err",
        )
        assert fetch_erratum_title_matches(sa_sync_conn) == []
