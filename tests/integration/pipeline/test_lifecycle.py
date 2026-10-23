"""Cycle de vie d'une publication : recalcul avec suppression, dissolution, purge."""

from functools import partial

import pytest
from sqlalchemy import text

from domain.merge import MergedEntity
from pipeline.transformation.publications.consolidation import RefreshVerdict
from pipeline.transformation.publications.lifecycle import (
    dissolve,
    purge_publications,
    refresh,
)
from tests.integration.helpers.contributions import insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_apc_payment, insert_publication
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.sources import insert_source_record
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject

_source_record = partial(
    insert_source_record, source="openalex", title="T", publication_year=2024, doc_type="article"
)


def _publication_exists(conn, publication_id) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM publications WHERE id = :id"), {"id": publication_id}
        ).first()
        is not None
    )


class TestRefresh:
    def test_publication_sans_source_supprimee(self, sa_sync_conn):
        pid = insert_publication(sa_sync_conn)

        assert refresh(sa_sync_conn, pid) == RefreshVerdict.NO_SOURCE
        assert not _publication_exists(sa_sync_conn, pid)

    def test_publication_avec_source_enregistree(self, sa_sync_conn):
        pid = insert_publication(sa_sync_conn)
        _source_record(sa_sync_conn, pid, source_id="w1")

        assert refresh(sa_sync_conn, pid) == RefreshVerdict.SAVED
        assert _publication_exists(sa_sync_conn, pid)


class TestDissolve:
    def test_paiements_redirection_et_suppression(self, sa_sync_conn):
        conn = sa_sync_conn
        dissoute = insert_publication(conn)
        successeur = insert_publication(conn)
        paiement = insert_apc_payment(conn, publication_id=dissoute, open_access_fee=True)

        dissolve(conn, dissoute, successeur)

        assert not _publication_exists(conn, dissoute)
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
        _source_record(conn, dissoute, source_id="w1")

        with pytest.raises(ValueError):
            dissolve(conn, dissoute, successeur)
        assert _publication_exists(conn, dissoute)


class TestPurge:
    @staticmethod
    def _publication(conn, *, source: bool, contribution: bool) -> int:
        pid = insert_publication(conn)
        if source:
            _source_record(conn, pid, source_id=f"w{pid}", marked=False)
        if contribution:
            insert_contribution(conn, pid, person_id=insert_person(conn, "Doe", first_name="Jane"))
        return pid

    def test_publication_sans_source_ou_sans_contribution_supprimee(self, sa_sync_conn):
        conn = sa_sync_conn
        sans_source = self._publication(conn, source=False, contribution=True)
        sans_contribution = self._publication(conn, source=True, contribution=False)
        complete = self._publication(conn, source=True, contribution=True)

        purge_publications(conn)

        assert not _publication_exists(conn, sans_source)
        assert not _publication_exists(conn, sans_contribution)
        assert _publication_exists(conn, complete)

    def test_limit_borne_le_lot(self, sa_sync_conn):
        conn = sa_sync_conn
        # Purge préalable pour un compte déterministe, annulée par le rollback du test.
        purge_publications(conn)
        for _ in range(3):
            insert_publication(conn)

        assert purge_publications(conn, limit=2) == 2
        assert purge_publications(conn, limit=2) == 1
        assert purge_publications(conn, limit=2) == 0

    def test_sujets_supprimes_en_cascade(self, sa_sync_conn):
        """`publication_subjects` reste limitée aux publications du périmètre sans filtre propre."""
        conn = sa_sync_conn
        pid = insert_publication(conn)
        insert_publication_subject(conn, pid, subject_id=insert_subject(conn, "vaches laitieres"))

        purge_publications(conn)

        assert (
            conn.execute(
                text("SELECT count(*) FROM publication_subjects WHERE publication_id = :p"),
                {"p": pid},
            ).scalar_one()
            == 0
        )
