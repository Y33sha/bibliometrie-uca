"""Cycle de vie d'une publication : recalcul avec suppression, dissolution, suppression des publications sans source."""

from functools import partial

import pytest
from sqlalchemy import text

from domain.merge import MergedEntity
from pipeline.transformation.publications.consolidation import RefreshVerdict
from pipeline.transformation.publications.lifecycle import (
    delete_publications_without_sources,
    dissolve,
    refresh,
)
from tests.integration.helpers.publications import insert_apc_payment, insert_publication
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.sources import insert_source_publication

_notice = partial(
    insert_source_publication, source="openalex", title="T", pub_year=2024, doc_type="article"
)


def _pub_exists(conn, pub_id) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM publications WHERE id = :id"), {"id": pub_id}).first()
        is not None
    )


class TestRefresh:
    def test_publication_sans_source_supprimee(self, sa_sync_conn):
        pid = insert_publication(sa_sync_conn)

        assert refresh(sa_sync_conn, pid) == RefreshVerdict.NO_SOURCE
        assert not _pub_exists(sa_sync_conn, pid)

    def test_publication_avec_source_enregistree(self, sa_sync_conn):
        pid = insert_publication(sa_sync_conn)
        _notice(sa_sync_conn, pid, source_id="w1")

        assert refresh(sa_sync_conn, pid) == RefreshVerdict.SAVED
        assert _pub_exists(sa_sync_conn, pid)


class TestDissolve:
    def test_paiements_redirection_et_suppression(self, sa_sync_conn):
        conn = sa_sync_conn
        dissoute = insert_publication(conn)
        successeur = insert_publication(conn)
        paiement = insert_apc_payment(conn, publication_id=dissoute, open_access_fee=True)

        dissolve(conn, dissoute, successeur)

        assert not _pub_exists(conn, dissoute)
        assert redirect_of(conn, MergedEntity.PUBLICATION, dissoute) == successeur
        assert (
            conn.execute(
                text("SELECT publication_id FROM apc_payments WHERE id = :id"), {"id": paiement}
            ).scalar_one()
            == successeur
        )

    def test_publication_avec_source_refusee(self, sa_sync_conn):
        conn = sa_sync_conn
        dissoute = insert_publication(conn)
        successeur = insert_publication(conn)
        _notice(conn, dissoute, source_id="w1")

        with pytest.raises(ValueError):
            dissolve(conn, dissoute, successeur)
        assert _pub_exists(conn, dissoute)


def test_seules_les_publications_sans_source_sont_supprimees(sa_sync_conn):
    conn = sa_sync_conn
    vide = insert_publication(conn)
    garnie = insert_publication(conn)
    _notice(conn, garnie, source_id="garnie", keys_dirty=False)

    assert delete_publications_without_sources(conn) == 1
    assert not _pub_exists(conn, vide)
    assert _pub_exists(conn, garnie)
