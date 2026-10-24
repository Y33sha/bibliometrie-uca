"""Tests du service d'audit (services/audit.py).

Vérifie deux comportements essentiels :
1. Hors contexte utilisateur (pipeline, scripts) → emit_event est no-op.
2. Dans un contexte utilisateur (requête HTTP) → l'événement est persisté.
"""

from functools import partial

import pytest
from sqlalchemy import text

from application.audit_log import (
    emit_event,
    get_current_user,
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
        """Hors contexte utilisateur : emit_event ne persiste rien."""
        emit_event(audit_repository(sa_sync_conn), "person.merged", "person", 1, {"source_id": 2})
        n = sa_sync_conn.execute(text("SELECT COUNT(*) AS n FROM audit_log")).scalar_one()
        assert n == 0

    def test_with_user_persists(self, sa_sync_conn):
        token = set_current_user("admin")
        try:
            emit_event(
                audit_repository(sa_sync_conn), "person.merged", "person", 1, {"source_id": 2}
            )
            row = sa_sync_conn.execute(
                text(
                    "SELECT event_type, aggregate_type, aggregate_id, payload, user_id "
                    "FROM audit_log ORDER BY id DESC LIMIT 1"
                )
            ).one()
        finally:
            reset_current_user(token)

        assert row.event_type == "person.merged"
        assert row.aggregate_type == "person"
        assert row.aggregate_id == 1
        assert row.payload == {"source_id": 2}
        assert row.user_id == "admin"

    def test_accepts_null_aggregate_id(self, sa_sync_conn):
        """Cas d'une entité supprimée sans équivalent survivant."""
        token = set_current_user("admin")
        try:
            emit_event(
                audit_repository(sa_sync_conn),
                "structure.deleted",
                "structure",
                None,
                {"name": "X"},
            )
            agg_id = sa_sync_conn.execute(
                text("SELECT aggregate_id FROM audit_log ORDER BY id DESC LIMIT 1")
            ).scalar_one()
            assert agg_id is None
        finally:
            reset_current_user(token)

    def test_default_payload_is_empty_object(self, sa_sync_conn):
        token = set_current_user("admin")
        try:
            emit_event(audit_repository(sa_sync_conn), "person.exclusion", "person", 42)
            payload = sa_sync_conn.execute(
                text("SELECT payload FROM audit_log ORDER BY id DESC LIMIT 1")
            ).scalar_one()
            assert payload == {}
        finally:
            reset_current_user(token)

    def test_multiple_events_in_order(self, sa_sync_conn):
        token = set_current_user("admin")
        try:
            repo = audit_repository(sa_sync_conn)
            emit_event(repo, "a.b", "person", 1)
            emit_event(repo, "c.d", "person", 2)
            rows = sa_sync_conn.execute(text("SELECT event_type FROM audit_log ORDER BY id")).all()
        finally:
            reset_current_user(token)
        assert [r.event_type for r in rows] == ["a.b", "c.d"]


class TestEndToEndServiceIntegration:
    """Vérifie que les services destructifs émettent bien les événements
    attendus quand un utilisateur est dans le contexte."""

    @pytest.fixture
    def sa_sync_conn(self, sa_sync_conn_owner):
        """Ces tests posent des publications, que le pipeline crée, puis exercent des opérations que l'API conduit — deux rôles dans une même transaction.

        Ils se connectent donc sous le propriétaire du schéma. Ce qu'ils éprouvent est l'enchaînement des services et l'émission de la trace, non la frontière des droits, tenue par les tests d'API et ceux du pipeline, qui se connectent chacun sous le rôle exerçant l'opération.
        """
        return sa_sync_conn_owner

    def _last_event(self, conn):
        return conn.execute(
            text(
                "SELECT event_type, aggregate_type, aggregate_id, payload, user_id "
                "FROM audit_log ORDER BY id DESC LIMIT 1"
            )
        ).one()

    def test_set_exclusion_emits_event(self, sa_sync_conn):
        from application.services.persons.core import set_exclusion
        from domain.persons.person import PersonExclusion
        from infrastructure.repositories import person_repository

        person_id = _person(sa_sync_conn)
        token = set_current_user("admin")
        try:
            set_exclusion(
                person_id,
                PersonExclusion.OUT_OF_PERIMETER,
                conn=sa_sync_conn,
                repo=person_repository(sa_sync_conn),
                perimeter_recompute=PublicationPerimeterRecompute(),
                audit_repo=audit_repository(sa_sync_conn),
            )
        finally:
            reset_current_user(token)

        row = sa_sync_conn.execute(
            text(
                "SELECT event_type, aggregate_id, payload, user_id "
                "FROM audit_log ORDER BY id DESC LIMIT 1"
            )
        ).one()
        assert row.event_type == "person.exclusion"
        assert row.aggregate_id == person_id
        assert row.payload == {"exclusion": "out_of_perimeter"}
        assert row.user_id == "admin"

    def test_set_exclusion_without_context_no_event(self, sa_sync_conn):
        """Confirme que hors contexte (pipeline, script), rien n'est audité
        même quand un service destructif est appelé."""
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
            audit_repo=audit_repository(sa_sync_conn),
        )

        n = sa_sync_conn.execute(text("SELECT COUNT(*) AS n FROM audit_log")).scalar_one()
        assert n == 0

    def test_mark_distinct_emits_only_on_actual_insert(self, sa_sync_conn):
        """mark_distinct est idempotent : un appel sur une paire déjà
        marquée ne doit pas générer d'événement supplémentaire."""
        from application.services.persons.core import mark_distinct
        from infrastructure.repositories import person_repository

        p1 = _person(sa_sync_conn, last_name="A", first_name="A")
        p2 = _person(sa_sync_conn, last_name="B", first_name="B")
        repo = person_repository(sa_sync_conn)
        audit_repo_ = audit_repository(sa_sync_conn)
        token = set_current_user("admin")
        try:
            mark_distinct(p1, p2, repo=repo, audit_repo=audit_repo_)
            mark_distinct(p1, p2, repo=repo, audit_repo=audit_repo_)
            mark_distinct(p2, p1, repo=repo, audit_repo=audit_repo_)
        finally:
            reset_current_user(token)

        n = sa_sync_conn.execute(
            text("SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'person.marked_distinct'")
        ).scalar_one()
        assert n == 1

    def test_merge_person_emits_event(self, sa_sync_conn):
        from application.services.persons.core import merge_person
        from infrastructure.repositories import person_repository

        target = _person(sa_sync_conn, last_name="A")
        source = _person(sa_sync_conn, last_name="B")
        token = set_current_user("admin")
        try:
            merge_person(
                target,
                source,
                repo=person_repository(sa_sync_conn),
                audit_repo=audit_repository(sa_sync_conn),
            )
        finally:
            reset_current_user(token)

        row = self._last_event(sa_sync_conn)
        assert row.event_type == "person.merged"
        assert row.aggregate_id == target
        assert row.payload == {"source_id": source}
        assert row.user_id == "admin"

    def test_name_form_confirm_emits_event(self, sa_sync_conn):
        from application.services.persons.core import update_name_form_status
        from infrastructure.repositories import contribution_repository, person_repository

        person_id = _person(sa_sync_conn)
        insert_person_name_form(
            sa_sync_conn, person_id, name_form="x x", sources=["hal"], status="pending"
        )
        token = set_current_user("admin")
        try:
            update_name_form_status(
                person_id,
                "x x",
                "confirmed",
                conn=sa_sync_conn,
                perimeter_recompute=PublicationPerimeterRecompute(),
                repo=person_repository(sa_sync_conn),
                contribution_repo=contribution_repository(sa_sync_conn),
                audit_repo=audit_repository(sa_sync_conn),
            )
        finally:
            reset_current_user(token)

        row = self._last_event(sa_sync_conn)
        assert row.event_type == "person_name_form.status_changed"
        assert row.aggregate_id == person_id
        assert row.payload == {"name_form": "x x", "status": "confirmed"}

    def test_name_form_reject_emits_event(self, sa_sync_conn):
        """Le rejet d'une forme (action « détacher l'intrus ») émet l'événement."""
        from application.services.persons.core import update_name_form_status
        from infrastructure.repositories import contribution_repository, person_repository

        person_id = _person(sa_sync_conn)
        insert_person_name_form(
            sa_sync_conn, person_id, name_form="x x", sources=["hal"], status="pending"
        )
        token = set_current_user("admin")
        try:
            update_name_form_status(
                person_id,
                "x x",
                "rejected",
                conn=sa_sync_conn,
                perimeter_recompute=PublicationPerimeterRecompute(),
                repo=person_repository(sa_sync_conn),
                contribution_repo=contribution_repository(sa_sync_conn),
                audit_repo=audit_repository(sa_sync_conn),
            )
        finally:
            reset_current_user(token)

        row = self._last_event(sa_sync_conn)
        assert row.event_type == "person_name_form.status_changed"
        assert row.payload == {"name_form": "x x", "status": "rejected"}

    def test_reject_pair_emits_event(self, sa_sync_conn):
        """Le détachement d'une paire (publication, personne) émet l'événement."""
        from application.services.contributions.core import reject_pair
        from infrastructure.repositories import contribution_repository

        person_id = _person(sa_sync_conn)
        publication_id = insert_publication(sa_sync_conn)
        token = set_current_user("admin")
        try:
            reject_pair(
                publication_id,
                person_id,
                conn=sa_sync_conn,
                perimeter_recompute=PublicationPerimeterRecompute(),
                repo=contribution_repository(sa_sync_conn),
                audit_repo=audit_repository(sa_sync_conn),
            )
        finally:
            reset_current_user(token)

        row = self._last_event(sa_sync_conn)
        assert row.event_type == "contribution.rejected"
        assert row.aggregate_type == "publication"
        assert row.aggregate_id == publication_id
        assert row.payload == {"person_id": person_id}
