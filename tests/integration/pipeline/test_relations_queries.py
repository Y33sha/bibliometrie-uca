"""Intégration : rapprochement par titre (signal #3) — erratums et preprints.

Valide sur vraie base `fetch_erratum_title_matches` (suffixe de titre) et
`fetch_preprint_title_matches` (titre identique), et leur garde d'ambiguïté commune : un seul parent
« substantiel » (hors formes de la même œuvre) doit porter le titre, sinon collision → abstention.
Le parent est désigné par son `publication_id` ; son DOI peut être absent (cible au corpus sans DOI).
"""

from infrastructure.queries.pipeline.relations import (
    fetch_erratum_title_matches,
    fetch_preprint_title_matches,
)
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
        parent = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/parent"
        )
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [
            (err, parent, "10.1/parent")
        ]

    def test_doiless_parent_still_matched(self, sa_sync_conn):
        # Le parent au corpus n'a pas de DOI : rapproché quand même, parent_doi None.
        parent = _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi=None)
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [(err, parent, None)]

    def test_two_substantive_same_title_blocked(self, sa_sync_conn):
        # Deux articles distincts au même titre = collision → abstention.
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
        # Le preprint partage le titre mais n'est pas un parent substantiel : on relie l'article.
        article = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/article"
        )
        _pub(sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/preprint")
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id) for m in matches] == [(err, article)]

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
            sa_sync_conn, doc_type="erratum", title_normalized=f"erratum to {short}", doi="10.1/err"
        )
        assert fetch_erratum_title_matches(sa_sync_conn) == []


class TestFetchPreprintTitleMatches:
    def test_unique_published_parent_matched(self, sa_sync_conn):
        # La version publiée suit le preprint (année + 1), titre identique.
        parent = _pub(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/pub",
            pub_year=2025,
        )
        pre = _pub(
            sa_sync_conn,
            doc_type="preprint",
            title_normalized=PARENT_TITLE,
            doi="10.1/pre",
            pub_year=2024,
        )
        matches = fetch_preprint_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [
            (pre, parent, "10.1/pub")
        ]

    def test_two_published_versions_blocked(self, sa_sync_conn):
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a")
        _pub(
            sa_sync_conn,
            doc_type="conference_paper",
            title_normalized=PARENT_TITLE,
            doi="10.1/b",
        )
        _pub(sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/pre")
        assert fetch_preprint_title_matches(sa_sync_conn) == []

    def test_dataset_does_not_block(self, sa_sync_conn):
        article = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/article"
        )
        _pub(sa_sync_conn, doc_type="dataset", title_normalized=PARENT_TITLE, doi="10.1/data")
        pre = _pub(sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/pre")
        matches = fetch_preprint_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id) for m in matches] == [(pre, article)]

    def test_parent_before_preprint_not_matched(self, sa_sync_conn):
        # Une publication antérieure au preprint n'est pas sa version publiée.
        _pub(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/old",
            pub_year=2022,
        )
        _pub(
            sa_sync_conn,
            doc_type="preprint",
            title_normalized=PARENT_TITLE,
            doi="10.1/pre",
            pub_year=2024,
        )
        assert fetch_preprint_title_matches(sa_sync_conn) == []
