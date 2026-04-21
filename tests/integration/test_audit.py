"""Tests du service d'audit (services/audit.py).

Vérifie deux comportements essentiels :
1. Hors contexte utilisateur (pipeline, scripts) → emit_event est no-op.
2. Dans un contexte utilisateur (requête HTTP) → l'événement est persisté.
"""

from application.audit import (
    emit_event,
    get_current_user,
    reset_current_user,
    set_current_user,
)
from infrastructure.repositories import async_person_repository


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
    def test_no_user_no_event(self, db):
        """Hors contexte utilisateur : emit_event ne persiste rien."""
        emit_event(db, "person.merged", "person", 1, {"source_id": 2})
        db.execute("SELECT COUNT(*) AS n FROM audit_log")
        assert db.fetchone()["n"] == 0

    def test_with_user_persists(self, db):
        token = set_current_user("admin")
        try:
            emit_event(db, "person.merged", "person", 1, {"source_id": 2})
            db.execute(
                "SELECT event_type, aggregate_type, aggregate_id, payload, user_id "
                "FROM audit_log ORDER BY id DESC LIMIT 1"
            )
            row = db.fetchone()
        finally:
            reset_current_user(token)

        assert row["event_type"] == "person.merged"
        assert row["aggregate_type"] == "person"
        assert row["aggregate_id"] == 1
        assert row["payload"] == {"source_id": 2}
        assert row["user_id"] == "admin"

    def test_accepts_null_aggregate_id(self, db):
        """Cas d'une entité supprimée sans équivalent survivant."""
        token = set_current_user("admin")
        try:
            emit_event(db, "structure.deleted", "structure", None, {"name": "X"})
            db.execute("SELECT aggregate_id FROM audit_log ORDER BY id DESC LIMIT 1")
            assert db.fetchone()["aggregate_id"] is None
        finally:
            reset_current_user(token)

    def test_default_payload_is_empty_object(self, db):
        token = set_current_user("admin")
        try:
            emit_event(db, "person.rejected", "person", 42)
            db.execute("SELECT payload FROM audit_log ORDER BY id DESC LIMIT 1")
            assert db.fetchone()["payload"] == {}
        finally:
            reset_current_user(token)

    def test_multiple_events_in_order(self, db):
        token = set_current_user("admin")
        try:
            emit_event(db, "a.b", "person", 1)
            emit_event(db, "c.d", "person", 2)
            db.execute("SELECT event_type FROM audit_log ORDER BY id")
            rows = db.fetchall()
        finally:
            reset_current_user(token)
        assert [r["event_type"] for r in rows] == ["a.b", "c.d"]


class TestEndToEndServiceIntegration:
    """Vérifie que les services destructifs émettent bien les événements
    attendus quand un utilisateur est dans le contexte."""

    async def _a_create_person(self, cur, last="X", first="X"):
        await cur.execute(
            """
            INSERT INTO persons (last_name, first_name,
                                 last_name_normalized, first_name_normalized)
            VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id
            """,
            (last, first, last, first),
        )
        return (await cur.fetchone())["id"]

    async def test_set_rejected_emits_event(self, async_db):
        from application.persons import set_rejected

        person_id = await self._a_create_person(async_db)
        token = set_current_user("admin")
        try:
            await set_rejected(async_db, person_id, True, repo=async_person_repository(async_db))
        finally:
            reset_current_user(token)

        await async_db.execute(
            "SELECT event_type, aggregate_id, payload, user_id "
            "FROM audit_log ORDER BY id DESC LIMIT 1"
        )
        row = await async_db.fetchone()
        assert row["event_type"] == "person.rejected"
        assert row["aggregate_id"] == person_id
        assert row["payload"] == {"rejected": True}
        assert row["user_id"] == "admin"

    async def test_set_rejected_without_context_no_event(self, async_db):
        """Confirme que hors contexte (pipeline, script), rien n'est audité
        même quand un service destructif est appelé."""
        from application.persons import set_rejected

        person_id = await self._a_create_person(async_db)
        await set_rejected(async_db, person_id, True, repo=async_person_repository(async_db))

        await async_db.execute("SELECT COUNT(*) AS n FROM audit_log")
        assert (await async_db.fetchone())["n"] == 0

    async def test_mark_distinct_emits_only_on_actual_insert(self, async_db):
        """mark_distinct est idempotent : un appel sur une paire déjà
        marquée ne doit pas générer d'événement supplémentaire."""
        from application.persons import mark_distinct

        p1 = await self._a_create_person(async_db, "A", "A")
        p2 = await self._a_create_person(async_db, "B", "B")
        repo = async_person_repository(async_db)
        token = set_current_user("admin")
        try:
            await mark_distinct(async_db, p1, p2, repo=repo)
            await mark_distinct(async_db, p1, p2, repo=repo)  # doublon → no-op
            await mark_distinct(async_db, p2, p1, repo=repo)  # même paire dans l'autre sens → no-op
        finally:
            reset_current_user(token)

        await async_db.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'person.marked_distinct'"
        )
        assert (await async_db.fetchone())["n"] == 1
