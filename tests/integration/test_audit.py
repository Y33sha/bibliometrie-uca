"""Tests du journal d'audit (`application/audit_log.py`).

Vérifie trois comportements :
1. Hors requête d'administration (pipeline, scripts) → `emit_event` ne consigne rien.
2. Dans une requête d'administration → l'événement rejoint la file de la requête, écrite dans `audit_log` avant le commit.
3. Un événement émis dans un bloc `discarded_events` → écarté avec l'écriture annulée qu'il décrit.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial

import pytest
from sqlalchemy import Connection, text

from application.audit_log import (
    discarded_events,
    emit_event,
    get_current_user,
    record_pending_events,
    reset_current_user,
    set_current_user,
)
from infrastructure.repositories import audit_repository
from pipeline.transformation.publications.publication_perimeter import (
    PublicationPerimeterRecompute,
)
from tests.integration.helpers.persons import insert_person, insert_person_name_form
from tests.integration.helpers.publications import insert_publication

# Personne « X X » par défaut, normalisée par `lower`.
_person = partial(insert_person, last_name="X", first_name="X", normalizer="lower")


@contextmanager
def _requete_admin(conn: Connection, user: str = "admin") -> Iterator[None]:
    """Rejoue le cycle d'une requête d'administration : la session de l'utilisatrice, puis l'écriture de sa file d'événements, comme `db_conn` avant son commit."""
    token = set_current_user(user)
    try:
        yield
        record_pending_events(audit_repository(conn))
    finally:
        reset_current_user(token)


def _count(conn: Connection) -> int:
    return conn.execute(text("SELECT COUNT(*) AS n FROM audit_log")).scalar_one()


def _last_event(conn: Connection):
    return conn.execute(
        text(
            "SELECT event_type, aggregate_type, aggregate_id, payload, user_id "
            "FROM audit_log ORDER BY id DESC LIMIT 1"
        )
    ).one()


@pytest.fixture
def sa_sync_conn(sa_sync_conn_app):
    """La trace d'audit est écrite par l'API, seule à en porter le droit.

    Ces tests se connectent donc sous son rôle. Le pipeline en est écarté : il ne prend aucune décision humaine, et pouvoir en déposer la trace ôterait à la table ce qu'elle vaut.
    """
    return sa_sync_conn_app


class TestCurrentUserContext:
    def test_default_is_none(self):
        assert get_current_user() is None

    def test_set_and_get(self):
        token = set_current_user("alice")
        try:
            assert get_current_user() == "alice"
        finally:
            reset_current_user(token)
        assert get_current_user() is None

    def test_nested_contexts_restore(self):
        token_outer = set_current_user("alice")
        try:
            token_inner = set_current_user("bob")
            try:
                assert get_current_user() == "bob"
            finally:
                reset_current_user(token_inner)
            assert get_current_user() == "alice"
        finally:
            reset_current_user(token_outer)
        assert get_current_user() is None


class TestEmitEvent:
    def test_no_user_no_event(self, sa_sync_conn):
        """Hors requête d'administration : rien n'est consigné."""
        emit_event("person.merged", "person", 1, {"source_id": 2})
        record_pending_events(audit_repository(sa_sync_conn))
        assert _count(sa_sync_conn) == 0

    def test_with_user_persists(self, sa_sync_conn):
        with _requete_admin(sa_sync_conn):
            emit_event("person.merged", "person", 1, {"source_id": 2})

        row = _last_event(sa_sync_conn)
        assert row.event_type == "person.merged"
        assert row.aggregate_type == "person"
        assert row.aggregate_id == 1
        assert row.payload == {"source_id": 2}
        assert row.user_id == "admin"

    def test_written_only_when_recorded(self, sa_sync_conn):
        """L'événement attend l'écriture de la file : une requête qui échoue n'en laisse aucun."""
        token = set_current_user("admin")
        try:
            emit_event("person.merged", "person", 1)
            assert _count(sa_sync_conn) == 0
        finally:
            reset_current_user(token)

    def test_accepts_null_aggregate_id(self, sa_sync_conn):
        """Cas d'une entité supprimée sans équivalent survivant."""
        with _requete_admin(sa_sync_conn):
            emit_event("structure.deleted", "structure", None, {"name": "X"})
        assert _last_event(sa_sync_conn).aggregate_id is None

    def test_default_payload_is_empty_object(self, sa_sync_conn):
        with _requete_admin(sa_sync_conn):
            emit_event("person.exclusion", "person", 42)
        assert _last_event(sa_sync_conn).payload == {}

    def test_multiple_events_in_order(self, sa_sync_conn):
        with _requete_admin(sa_sync_conn):
            emit_event("a.b", "person", 1)
            emit_event("c.d", "person", 2)
        rows = sa_sync_conn.execute(text("SELECT event_type FROM audit_log ORDER BY id")).all()
        assert [r.event_type for r in rows] == ["a.b", "c.d"]

    def test_discarded_events_are_not_written(self, sa_sync_conn):
        with _requete_admin(sa_sync_conn):
            emit_event("a.b", "person", 1)
            with discarded_events():
                emit_event("c.d", "person", 2)
        rows = sa_sync_conn.execute(text("SELECT event_type FROM audit_log ORDER BY id")).all()
        assert [r.event_type for r in rows] == ["a.b"]


class TestEndToEndServiceIntegration:
    """Vérifie que les services émettent les événements attendus dans une requête d'administration."""

    @pytest.fixture
    def sa_sync_conn(self, sa_sync_conn_owner):
        """Ces tests posent des publications, que le pipeline crée, puis exercent des opérations que l'API conduit — deux rôles dans une même transaction.

        Ils se connectent donc sous le propriétaire du schéma. Ce qu'ils éprouvent est l'enchaînement des services et l'émission de la trace, non la frontière des droits, tenue par les tests d'API et ceux du pipeline, qui se connectent chacun sous le rôle exerçant l'opération.
        """
        return sa_sync_conn_owner

    def test_set_exclusion_emits_event(self, sa_sync_conn):
        from application.services.persons.core import set_exclusion
        from domain.persons.person import PersonExclusion
        from infrastructure.repositories import person_repository

        person_id = _person(sa_sync_conn)
        with _requete_admin(sa_sync_conn):
            set_exclusion(
                person_id,
                PersonExclusion.OUT_OF_PERIMETER,
                conn=sa_sync_conn,
                repo=person_repository(sa_sync_conn),
                perimeter_recompute=PublicationPerimeterRecompute(),
            )

        row = _last_event(sa_sync_conn)
        assert row.event_type == "person.exclusion"
        assert row.aggregate_id == person_id
        assert row.payload == {"exclusion": "out_of_perimeter"}
        assert row.user_id == "admin"

    def test_set_exclusion_without_context_no_event(self, sa_sync_conn):
        """Hors requête d'administration (pipeline, script), rien n'est consigné, même quand un service écrit."""
        from application.services.persons.core import set_exclusion
        from domain.persons.person import PersonExclusion
        from infrastructure.repositories import person_repository

        person_id = _person(sa_sync_conn)
        set_exclusion(
            person_id,
            PersonExclusion.NOT_A_PERSON,
            conn=sa_sync_conn,
            repo=person_repository(sa_sync_conn),
            perimeter_recompute=PublicationPerimeterRecompute(),
        )
        record_pending_events(audit_repository(sa_sync_conn))
        assert _count(sa_sync_conn) == 0

    def test_mark_distinct_emits_only_on_actual_insert(self, sa_sync_conn):
        """`mark_distinct` est idempotent : un appel sur une paire déjà marquée n'émet pas d'événement supplémentaire."""
        from application.services.persons.core import mark_distinct
        from infrastructure.repositories import person_repository

        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        repo = person_repository(sa_sync_conn)
        with _requete_admin(sa_sync_conn):
            mark_distinct(p1, p2, repo=repo)
            mark_distinct(p1, p2, repo=repo)
            mark_distinct(p2, p1, repo=repo)

        n = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'person.marked_distinct'")
        ).scalar_one()
        assert n == 1

    def test_merge_person_emits_event(self, sa_sync_conn):
        from application.services.persons.core import merge_person
        from infrastructure.repositories import person_repository

        target = _person(sa_sync_conn, last_name="A")
        source = _person(sa_sync_conn, last_name="B")
        with _requete_admin(sa_sync_conn):
            merge_person(target, source, repo=person_repository(sa_sync_conn))

        row = _last_event(sa_sync_conn)
        assert row.event_type == "person.merged"
        assert row.aggregate_id == target
        assert row.payload == {"source_id": source}
        assert row.user_id == "admin"

    @pytest.mark.parametrize("status", ["confirmed", "rejected"])
    def test_name_form_status_emits_event(self, sa_sync_conn, status):
        """La confirmation comme le rejet d'une forme (action « détacher l'intrus ») émettent l'événement."""
        from application.services.persons.core import update_name_form_status
        from infrastructure.repositories import contribution_repository, person_repository

        person_id = _person(sa_sync_conn)
        insert_person_name_form(
            sa_sync_conn, person_id, name_form="x x", sources=["hal"], status="pending"
        )
        with _requete_admin(sa_sync_conn):
            update_name_form_status(
                person_id,
                "x x",
                status,
                repo=person_repository(sa_sync_conn),
                contribution_repo=contribution_repository(sa_sync_conn),
            )

        row = _last_event(sa_sync_conn)
        assert row.event_type == "person_name_form.status_changed"
        assert row.aggregate_id == person_id
        assert row.payload == {"name_form": "x x", "status": status}

    def test_reject_pair_emits_event(self, sa_sync_conn):
        """Le détachement d'une paire (publication, personne) émet l'événement."""
        from application.services.contributions.core import reject_pair
        from infrastructure.repositories import contribution_repository

        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        with _requete_admin(sa_sync_conn):
            reject_pair(
                publication_id,
                person_id,
                conn=sa_sync_conn,
                perimeter_recompute=PublicationPerimeterRecompute(),
                repo=contribution_repository(sa_sync_conn),
            )

        row = _last_event(sa_sync_conn)
        assert row.event_type == "contribution.rejected"
        assert row.aggregate_type == "publication"
        assert row.aggregate_id == publication_id
        assert row.payload == {"person_id": person_id}

    def test_serial_type_preview_emits_nothing(self, sa_sync_conn):
        """L'aperçu d'un changement de type annule son écriture : aucun événement n'en reste."""
        from application.services.serials.core import preview_type_change_impact
        from domain.serials.serial import SerialType
        from infrastructure.repositories import serial_repository
        from pipeline.transformation.publishing.serials.serial_merge import SerialRecompute
        from tests.integration.helpers.serials import insert_serial

        serial_id = insert_serial(sa_sync_conn, title="Revue X")
        with _requete_admin(sa_sync_conn):
            preview_type_change_impact(
                serial_id,
                serial_type=SerialType.MEDIA,
                conn=sa_sync_conn,
                repo=serial_repository(sa_sync_conn),
                recompute=SerialRecompute(),
            )
        assert _count(sa_sync_conn) == 0
