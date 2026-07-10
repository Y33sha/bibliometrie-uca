"""Tests du service d'audit (services/audit.py).

Vérifie deux comportements essentiels :
1. Hors contexte utilisateur (pipeline, scripts) → emit_event est no-op.
2. Dans un contexte utilisateur (requête HTTP) → l'événement est persisté.
"""

from sqlalchemy import text

from application.audit import (
    emit_event,
    get_current_user,
    reset_current_user,
    set_current_user,
)
from infrastructure.repositories import audit_repository


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
            emit_event(audit_repository(sa_sync_conn), "person.rejected", "person", 42)
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

    def _create_person(self, conn, last="X", first="X"):
        return conn.execute(
            text(
                "INSERT INTO persons (last_name, first_name, "
                "                     last_name_normalized, first_name_normalized) "
                "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
            ),
            {"l": last, "f": first},
        ).scalar_one()

    def _create_publication(self, conn):
        return conn.execute(
            text(
                "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                "VALUES ('X', 'x', 2024, CAST('article' AS doc_type)) RETURNING id"
            )
        ).scalar_one()

    def _last_event(self, conn):
        return conn.execute(
            text(
                "SELECT event_type, aggregate_type, aggregate_id, payload, user_id "
                "FROM audit_log ORDER BY id DESC LIMIT 1"
            )
        ).one()

    def test_set_rejected_emits_event(self, sa_sync_conn):
        from application.services.persons.core import set_rejected
        from infrastructure.repositories import person_repository

        person_id = self._create_person(sa_sync_conn)
        token = set_current_user("admin")
        try:
            set_rejected(
                person_id,
                True,
                repo=person_repository(sa_sync_conn),
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
        assert row.event_type == "person.rejected"
        assert row.aggregate_id == person_id
        assert row.payload == {"rejected": True}
        assert row.user_id == "admin"

    def test_set_rejected_without_context_no_event(self, sa_sync_conn):
        """Confirme que hors contexte (pipeline, script), rien n'est audité
        même quand un service destructif est appelé."""
        from application.services.persons.core import set_rejected
        from infrastructure.repositories import person_repository

        person_id = self._create_person(sa_sync_conn)
        set_rejected(
            person_id,
            True,
            repo=person_repository(sa_sync_conn),
            audit_repo=audit_repository(sa_sync_conn),
        )

        n = sa_sync_conn.execute(text("SELECT COUNT(*) AS n FROM audit_log")).scalar_one()
        assert n == 0

    def test_mark_distinct_emits_only_on_actual_insert(self, sa_sync_conn):
        """mark_distinct est idempotent : un appel sur une paire déjà
        marquée ne doit pas générer d'événement supplémentaire."""
        from application.services.persons.core import mark_distinct
        from infrastructure.repositories import person_repository

        def _mk(last):
            return sa_sync_conn.execute(
                text(
                    "INSERT INTO persons (last_name, first_name, "
                    "last_name_normalized, first_name_normalized) "
                    "VALUES (:l, :l, lower(:l), lower(:l)) RETURNING id"
                ),
                {"l": last},
            ).scalar_one()

        p1 = _mk("A")
        p2 = _mk("B")
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

        target = self._create_person(sa_sync_conn, last="A")
        source = self._create_person(sa_sync_conn, last="B")
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
        from infrastructure.repositories import person_repository

        person_id = self._create_person(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
                "VALUES ('x x', :pid, ARRAY['hal'], 'pending')"
            ),
            {"pid": person_id},
        )
        token = set_current_user("admin")
        try:
            update_name_form_status(
                person_id,
                "x x",
                "confirmed",
                repo=person_repository(sa_sync_conn),
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
        from infrastructure.repositories import person_repository

        person_id = self._create_person(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO person_name_forms (name_form, person_id, sources, status) "
                "VALUES ('x x', :pid, ARRAY['hal'], 'pending')"
            ),
            {"pid": person_id},
        )
        token = set_current_user("admin")
        try:
            update_name_form_status(
                person_id,
                "x x",
                "rejected",
                repo=person_repository(sa_sync_conn),
                audit_repo=audit_repository(sa_sync_conn),
            )
        finally:
            reset_current_user(token)

        row = self._last_event(sa_sync_conn)
        assert row.event_type == "person_name_form.status_changed"
        assert row.payload == {"name_form": "x x", "status": "rejected"}

    def test_reject_pair_emits_event(self, sa_sync_conn):
        """Le détachement d'une paire (publication, personne) émet l'événement."""
        from application.services.authorships.core import reject_pair
        from infrastructure.repositories import authorship_repository

        person_id = self._create_person(sa_sync_conn)
        pub_id = self._create_publication(sa_sync_conn)
        token = set_current_user("admin")
        try:
            reject_pair(
                pub_id,
                person_id,
                repo=authorship_repository(sa_sync_conn),
                audit_repo=audit_repository(sa_sync_conn),
            )
        finally:
            reset_current_user(token)

        row = self._last_event(sa_sync_conn)
        assert row.event_type == "authorship.rejected"
        assert row.aggregate_type == "publication"
        assert row.aggregate_id == pub_id
        assert row.payload == {"person_id": person_id}
