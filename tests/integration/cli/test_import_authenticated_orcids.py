"""Statut `authenticated` : garde du trigger et écritures de l'import des ORCID authentifiés.

Le statut `authenticated` indique qu'un chercheur a lui-même authentifié son ORCID. Le trigger `protect_authenticated_identifier` en fait un statut réservé (seul l'import dédié le pose) et définitif (aucun changement de statut, même par l'administration).
"""

from collections import Counter
from functools import partial

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from interfaces.cli.maintenance.import_authenticated_orcids import (
    AuthenticateOrcidOutcome,
    authenticate_orcid,
    authenticate_orcids,
    orcid_holders,
    rh_emails_to_person_ids,
)
from tests.integration.helpers.persons import insert_person, insert_person_identifier

# Identifiant ORCID.
_orcid = partial(insert_person_identifier, id_type="orcid")

_ORCID = "0000-0001-5100-3736"
_ORCID_B = "0000-0001-5166-5617"


def _status_of(conn, person_id, orcid):
    return conn.execute(
        text(
            "SELECT CAST(status AS text) FROM person_identifiers "
            "WHERE id_type = 'orcid' AND id_value = :v AND person_id = :p"
        ),
        {"v": orcid, "p": person_id},
    ).scalar_one()


def test_lectures_sur_base_vide(sa_sync_conn):
    """Les lectures couplées au schéma tournent sans buter sur une colonne périmée."""
    assert rh_emails_to_person_ids(sa_sync_conn) == {}
    assert orcid_holders(sa_sync_conn, [_ORCID]) == {}


class TestTriggerGuard:
    def test_insert_authenticated_blocked_without_flag(self, sa_sync_conn):
        person = insert_person(sa_sync_conn)
        with pytest.raises(DBAPIError):
            with sa_sync_conn.begin_nested():
                _orcid(sa_sync_conn, person, id_value=_ORCID, status="authenticated")

    def test_update_to_authenticated_blocked_without_flag(self, sa_sync_conn):
        person = insert_person(sa_sync_conn)
        _orcid(sa_sync_conn, person, id_value=_ORCID, status="pending")
        with pytest.raises(DBAPIError):
            with sa_sync_conn.begin_nested():
                sa_sync_conn.execute(
                    text(
                        "UPDATE person_identifiers SET status = 'authenticated' "
                        "WHERE id_type = 'orcid' AND id_value = :v"
                    ),
                    {"v": _ORCID},
                )

    def test_authenticated_cannot_be_degraded(self, sa_sync_conn):
        person = insert_person(sa_sync_conn)
        authenticate_orcids(sa_sync_conn, [(person, _ORCID)])
        for target in ("pending", "confirmed", "rejected"):
            with pytest.raises(DBAPIError):
                with sa_sync_conn.begin_nested():
                    sa_sync_conn.execute(
                        text(
                            "UPDATE person_identifiers SET status = "
                            "CAST(:s AS identifier_status) "
                            "WHERE id_type = 'orcid' AND id_value = :v"
                        ),
                        {"s": target, "v": _ORCID},
                    )
        assert _status_of(sa_sync_conn, person, _ORCID) == "authenticated"

    def test_person_id_change_allowed_when_status_kept(self, sa_sync_conn):
        """Le trigger permet de déplacer l'identifiant vers une autre personne, comme le fait une fusion, quand le statut reste."""
        source = insert_person(sa_sync_conn, "Source")
        target = insert_person(sa_sync_conn, "Target")
        authenticate_orcids(sa_sync_conn, [(source, _ORCID)])
        sa_sync_conn.execute(
            text(
                "UPDATE person_identifiers SET person_id = :t "
                "WHERE id_type = 'orcid' AND id_value = :v"
            ),
            {"t": target, "v": _ORCID},
        )
        assert _status_of(sa_sync_conn, target, _ORCID) == "authenticated"


class TestAuthenticateOrcid:
    def test_requires_flag(self, sa_sync_conn):
        person = insert_person(sa_sync_conn)
        with pytest.raises(DBAPIError):
            with sa_sync_conn.begin_nested():
                authenticate_orcid(sa_sync_conn, person, _ORCID)

    def test_inserts_when_missing(self, sa_sync_conn):
        person = insert_person(sa_sync_conn)
        assert authenticate_orcids(sa_sync_conn, [(person, _ORCID)]) == Counter(
            {AuthenticateOrcidOutcome.INSERTED: 1}
        )
        assert _status_of(sa_sync_conn, person, _ORCID) == "authenticated"

    def test_upgrades_same_person(self, sa_sync_conn):
        person = insert_person(sa_sync_conn)
        _orcid(sa_sync_conn, person, id_value=_ORCID, status="confirmed")
        assert authenticate_orcids(sa_sync_conn, [(person, _ORCID)]) == Counter(
            {AuthenticateOrcidOutcome.UPGRADED: 1}
        )
        assert _status_of(sa_sync_conn, person, _ORCID) == "authenticated"

    def test_reassigns_other_person(self, sa_sync_conn):
        holder = insert_person(sa_sync_conn, "Holder")
        owner = insert_person(sa_sync_conn, "Owner")
        _orcid(sa_sync_conn, holder, id_value=_ORCID, status="pending")
        assert orcid_holders(sa_sync_conn, [_ORCID]) == {_ORCID: (holder, "pending")}
        assert authenticate_orcids(sa_sync_conn, [(owner, _ORCID)]) == Counter(
            {AuthenticateOrcidOutcome.REASSIGNED: 1}
        )
        assert _status_of(sa_sync_conn, owner, _ORCID) == "authenticated"

    def test_import_is_idempotent(self, sa_sync_conn):
        p1 = insert_person(sa_sync_conn, "One")
        p2 = insert_person(sa_sync_conn, "Two")
        _orcid(sa_sync_conn, p2, id_value=_ORCID_B, status="pending")
        entries = [(p1, _ORCID), (p2, _ORCID_B)]

        first = authenticate_orcids(sa_sync_conn, entries)
        assert first == Counter(
            {AuthenticateOrcidOutcome.INSERTED: 1, AuthenticateOrcidOutcome.UPGRADED: 1}
        )
        second = authenticate_orcids(sa_sync_conn, entries)
        assert second == Counter({AuthenticateOrcidOutcome.NOOP: 2})
