"""Intégration : passe de réconciliation des composantes (merge-only).

Valide le SQL neuf (voisinage 1-hop, fetch dirty, clear) sur vraie base, et le bout-en-bout `run()` (fusion + nettoyage du drapeau) — `conn.commit` neutralisé pour rester dans la transaction rollbackée.
"""

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.pipeline.publications.reconcile_components import run
from infrastructure.queries.pipeline.publications_reconciliation import (
    PgPublicationsReconciliationQueries,
    fetch_dirty_source_publication_ids,
    fetch_reconciliation_universe,
)
from infrastructure.repositories import publication_repository

logger = logging.getLogger("test_reconcile_components")


def _seed_pub(conn, doi=None) -> int:
    return publication_repository(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        pub_year=2024,
        doi=doi,
        oa_status="unknown",
        journal_id=None,
        container_title=None,
        language=None,
    )


def _seed_sp(conn, *, source_id, publication_id=None, doi=None, external_ids=None, keys_dirty=True):
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, title, pub_year, doc_type, doi, external_ids,
             publication_id, keys_dirty)
        VALUES ('openalex', :sid, 'T', 2024, 'article', :doi, :ext, :pid, :dirty)
        RETURNING id
    """).bindparams(bindparam("ext", type_=JSONB))
    return conn.execute(
        stmt,
        {
            "sid": source_id,
            "doi": doi,
            "ext": external_ids or {},
            "pid": publication_id,
            "dirty": keys_dirty,
        },
    ).scalar_one()


def _pub_exists(conn, pub_id) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM publications WHERE id = :id"), {"id": pub_id}).first()
        is not None
    )


def _sp_state(conn, sp_id) -> tuple:
    return conn.execute(
        text("SELECT publication_id, keys_dirty FROM source_publications WHERE id = :id"),
        {"id": sp_id},
    ).one()


class TestUniverse:
    def test_fetches_dirty_and_one_hop_neighbor(self, sa_sync_conn):
        """Le voisinage = SP dirty + SP non-dirty partageant une clé ; ignore les non-liées."""
        conn = sa_sync_conn
        pub_a = _seed_pub(conn, doi="10.1/x")
        pub_b = _seed_pub(conn, doi="10.1/x")
        unrelated_pub = _seed_pub(conn, doi="10.9/z")
        dirty = _seed_sp(conn, source_id="a", publication_id=pub_a, doi="10.1/x", keys_dirty=True)
        neighbor = _seed_sp(
            conn, source_id="b", publication_id=pub_b, doi="10.1/x", keys_dirty=False
        )
        _seed_sp(conn, source_id="c", publication_id=unrelated_pub, doi="10.9/z", keys_dirty=False)

        universe = {r.id for r in fetch_reconciliation_universe(conn)}
        assert universe == {dirty, neighbor}

    def test_neighbor_by_hal_id(self, sa_sync_conn):
        conn = sa_sync_conn
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        dirty = _seed_sp(
            conn, source_id="a", publication_id=pub_a, external_ids={"hal_id": ["hal-1"]}
        )
        neighbor = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            external_ids={"hal_id": ["hal-1", "hal-2"]},
            keys_dirty=False,
        )
        assert {r.id for r in fetch_reconciliation_universe(conn)} == {dirty, neighbor}

    def test_dirty_orphan_excluded(self, sa_sync_conn):
        """Une SP dirty sans publication n'est pas un seed (rien à réconcilier)."""
        conn = sa_sync_conn
        _seed_sp(conn, source_id="orphan", publication_id=None, doi="10.1/x", keys_dirty=True)
        assert fetch_dirty_source_publication_ids(conn) == []


class TestEndToEnd:
    def test_two_pubs_sharing_doi_merged(self, sa_sync_conn, monkeypatch):
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn, doi="10.1/x")
        pub_b = _seed_pub(conn, doi="10.1/x")
        sp_a = _seed_sp(conn, source_id="a", publication_id=pub_a, doi="10.1/x")
        sp_b = _seed_sp(conn, source_id="b", publication_id=pub_b, doi="10.1/x")

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            pub_repo=publication_repository(conn),
        )

        # Ancre = publication de la SP au plus petit id (sp_a < sp_b → pub_a).
        anchor, absorbed = (pub_a, pub_b) if sp_a < sp_b else (pub_b, pub_a)
        assert _pub_exists(conn, anchor)
        assert not _pub_exists(conn, absorbed)
        assert _sp_state(conn, sp_a) == (anchor, False)
        assert _sp_state(conn, sp_b) == (anchor, False)

    def test_distinct_dois_not_merged(self, sa_sync_conn, monkeypatch):
        """Deux pubs à DOI distincts partageant un hal_id : pas de fusion (cannot-link DOI)."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn, doi="10.1/x")
        pub_b = _seed_pub(conn, doi="10.2/y")
        sp_a = _seed_sp(
            conn,
            source_id="a",
            publication_id=pub_a,
            doi="10.1/x",
            external_ids={"hal_id": ["hal-1"]},
        )
        sp_b = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            doi="10.2/y",
            external_ids={"hal_id": ["hal-1"]},
        )

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            pub_repo=publication_repository(conn),
        )

        assert _pub_exists(conn, pub_a)
        assert _pub_exists(conn, pub_b)
        # Drapeaux nettoyés malgré l'absence de fusion (les SP ont été réconciliées).
        assert _sp_state(conn, sp_a)[1] is False
        assert _sp_state(conn, sp_b)[1] is False
