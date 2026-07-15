"""Garde d'invariant du statut `authenticated` (trigger) + chemin d'import repository.

Le statut `authenticated` atteste qu'un chercheur a lui-même authentifié son ORCID. Le
trigger `protect_authenticated_identifier` en fait un statut réservé (seul l'import dédié
le pose) et immuable (aucune dégradation, même admin). L'écriture passe exclusivement par
`begin_authenticated_orcid_import` + `authenticate_orcid`.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from infrastructure.repositories import person_repository

_ORCID = "0000-0001-5100-3736"
_ORCID_B = "0000-0001-5166-5617"


def _create_person(conn, last="A", first="Z"):
    return (
        conn.execute(
            text(
                "INSERT INTO persons "
                "(last_name, first_name, last_name_normalized, first_name_normalized) "
                "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
            ),
            {"l": last, "f": first},
        )
        .one()
        .id
    )


def _insert_orcid(conn, person_id, orcid, status):
    conn.execute(
        text(
            "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
            "VALUES (:p, 'orcid', :v, 'auto', CAST(:s AS identifier_status))"
        ),
        {"p": person_id, "v": orcid, "s": status},
    )


def _status_of(conn, person_id, orcid):
    return conn.execute(
        text(
            "SELECT CAST(status AS text) FROM person_identifiers "
            "WHERE id_type = 'orcid' AND id_value = :v AND person_id = :p"
        ),
        {"v": orcid, "p": person_id},
    ).scalar_one()


class TestTriggerGuard:
    def test_insert_authenticated_blocked_without_flag(self, sa_sync_conn):
        person = _create_person(sa_sync_conn)
        with pytest.raises(DBAPIError):
            with sa_sync_conn.begin_nested():
                _insert_orcid(sa_sync_conn, person, _ORCID, "authenticated")

    def test_update_to_authenticated_blocked_without_flag(self, sa_sync_conn):
        person = _create_person(sa_sync_conn)
        _insert_orcid(sa_sync_conn, person, _ORCID, "pending")
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
        person = _create_person(sa_sync_conn)
        repo = person_repository(sa_sync_conn)
        repo.begin_authenticated_orcid_import()
        repo.authenticate_orcid(person, _ORCID)
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
        """Une fusion déplace l'identifiant (person_id) sans toucher au statut : permis."""
        source = _create_person(sa_sync_conn, last="Source")
        target = _create_person(sa_sync_conn, last="Target")
        repo = person_repository(sa_sync_conn)
        repo.begin_authenticated_orcid_import()
        repo.authenticate_orcid(source, _ORCID)
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
        person = _create_person(sa_sync_conn)
        repo = person_repository(sa_sync_conn)
        with pytest.raises(DBAPIError):
            with sa_sync_conn.begin_nested():
                repo.authenticate_orcid(person, _ORCID)

    def test_inserts_when_missing(self, sa_sync_conn):
        person = _create_person(sa_sync_conn)
        repo = person_repository(sa_sync_conn)
        repo.begin_authenticated_orcid_import()
        assert repo.authenticate_orcid(person, _ORCID) == "inserted"
        assert _status_of(sa_sync_conn, person, _ORCID) == "authenticated"

    def test_upgrades_same_person(self, sa_sync_conn):
        person = _create_person(sa_sync_conn)
        _insert_orcid(sa_sync_conn, person, _ORCID, "confirmed")
        repo = person_repository(sa_sync_conn)
        repo.begin_authenticated_orcid_import()
        assert repo.authenticate_orcid(person, _ORCID) == "upgraded"
        assert _status_of(sa_sync_conn, person, _ORCID) == "authenticated"

    def test_reassigns_other_person(self, sa_sync_conn):
        holder = _create_person(sa_sync_conn, last="Holder")
        owner = _create_person(sa_sync_conn, last="Owner")
        _insert_orcid(sa_sync_conn, holder, _ORCID, "pending")
        repo = person_repository(sa_sync_conn)
        repo.begin_authenticated_orcid_import()
        assert repo.authenticate_orcid(owner, _ORCID) == "reassigned"
        assert _status_of(sa_sync_conn, owner, _ORCID) == "authenticated"

    def test_noop_when_already_authenticated(self, sa_sync_conn):
        person = _create_person(sa_sync_conn)
        repo = person_repository(sa_sync_conn)
        repo.begin_authenticated_orcid_import()
        repo.authenticate_orcid(person, _ORCID)
        assert repo.authenticate_orcid(person, _ORCID) == "noop"

    def test_import_is_idempotent(self, sa_sync_conn):
        from collections import Counter

        from application.ports.repositories.person_repository import AuthenticateOrcidOutcome
        from application.services.persons.core import authenticate_orcids

        p1 = _create_person(sa_sync_conn, last="One")
        p2 = _create_person(sa_sync_conn, last="Two")
        _insert_orcid(sa_sync_conn, p2, _ORCID_B, "pending")
        entries = [(p1, _ORCID), (p2, _ORCID_B)]

        repo = person_repository(sa_sync_conn)
        first = authenticate_orcids(entries, repo=repo)
        assert first == Counter(
            {AuthenticateOrcidOutcome.INSERTED: 1, AuthenticateOrcidOutcome.UPGRADED: 1}
        )
        second = authenticate_orcids(entries, repo=repo)
        assert second == Counter({AuthenticateOrcidOutcome.NOOP: 2})
