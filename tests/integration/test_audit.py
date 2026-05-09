"""Tests du service d'audit (services/audit.py).

Vérifie deux comportements essentiels :
1. Hors contexte utilisateur (pipeline, scripts) → emit_event est no-op.
2. Dans un contexte utilisateur (requête HTTP) → l'événement est persisté.

Le dernier bloc valide la branche SQLAlchemy de `async_emit_event`
(cohabitation pendant le chantier sqlalchemy-core-adoption).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from application.audit import (
    async_emit_event,
    emit_event,
    get_current_user,
    reset_current_user,
    set_current_user,
)
from infrastructure.db.tables import audit_log
from infrastructure.repositories import (
    async_audit_repository,
    async_person_repository,
    audit_repository,
)


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
        emit_event(audit_repository(db), "person.merged", "person", 1, {"source_id": 2})
        db.execute("SELECT COUNT(*) AS n FROM audit_log")
        assert db.fetchone()["n"] == 0

    def test_with_user_persists(self, db):
        token = set_current_user("admin")
        try:
            emit_event(audit_repository(db), "person.merged", "person", 1, {"source_id": 2})
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
            emit_event(audit_repository(db), "structure.deleted", "structure", None, {"name": "X"})
            db.execute("SELECT aggregate_id FROM audit_log ORDER BY id DESC LIMIT 1")
            assert db.fetchone()["aggregate_id"] is None
        finally:
            reset_current_user(token)

    def test_default_payload_is_empty_object(self, db):
        token = set_current_user("admin")
        try:
            emit_event(audit_repository(db), "person.rejected", "person", 42)
            db.execute("SELECT payload FROM audit_log ORDER BY id DESC LIMIT 1")
            assert db.fetchone()["payload"] == {}
        finally:
            reset_current_user(token)

    def test_multiple_events_in_order(self, db):
        token = set_current_user("admin")
        try:
            repo = audit_repository(db)
            emit_event(repo, "a.b", "person", 1)
            emit_event(repo, "c.d", "person", 2)
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
            await set_rejected(
                async_db,
                person_id,
                True,
                repo=async_person_repository(async_db),
                audit_repo=async_audit_repository(async_db),
            )
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
        await set_rejected(
            async_db,
            person_id,
            True,
            repo=async_person_repository(async_db),
            audit_repo=async_audit_repository(async_db),
        )

        await async_db.execute("SELECT COUNT(*) AS n FROM audit_log")
        assert (await async_db.fetchone())["n"] == 0

    def test_mark_distinct_emits_only_on_actual_insert(self, db):
        """mark_distinct est idempotent : un appel sur une paire déjà
        marquée ne doit pas générer d'événement supplémentaire."""
        from application.persons import mark_distinct
        from infrastructure.repositories import audit_repository, person_repository

        def _mk(last):
            db.execute(
                "INSERT INTO persons (last_name, first_name, "
                "last_name_normalized, first_name_normalized) "
                "VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id",
                (last, last, last, last),
            )
            return db.fetchone()["id"]

        p1 = _mk("A")
        p2 = _mk("B")
        repo = person_repository(db)
        audit_repo_ = audit_repository(db)
        token = set_current_user("admin")
        try:
            mark_distinct(db, p1, p2, repo=repo, audit_repo=audit_repo_)
            mark_distinct(db, p1, p2, repo=repo, audit_repo=audit_repo_)  # doublon
            mark_distinct(db, p2, p1, repo=repo, audit_repo=audit_repo_)  # autre sens
        finally:
            reset_current_user(token)

        db.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE event_type = 'person.marked_distinct'"
        )
        assert db.fetchone()["n"] == 1


class TestAsyncEmitEventViaSAConnection:
    """Vérifie la branche SA de `PgAsyncAuditRepository` (chantier
    sqlalchemy-core-adoption — cohabitation pendant la phase 1)."""

    async def test_persists_via_sa_connection(self, sa_conn: AsyncConnection):
        token = set_current_user("admin")
        try:
            await async_emit_event(
                async_audit_repository(sa_conn),
                "person.merged",
                "person",
                42,
                {"source_id": 7},
            )
            result = await sa_conn.execute(
                select(
                    audit_log.c.event_type,
                    audit_log.c.aggregate_type,
                    audit_log.c.aggregate_id,
                    audit_log.c.payload,
                    audit_log.c.user_id,
                )
                .order_by(audit_log.c.id.desc())
                .limit(1)
            )
            row = result.one()
        finally:
            reset_current_user(token)

        assert row.event_type == "person.merged"
        assert row.aggregate_type == "person"
        assert row.aggregate_id == 42
        assert row.payload == {"source_id": 7}
        assert row.user_id == "admin"

    async def test_no_user_no_event_via_sa(self, sa_conn: AsyncConnection):
        await async_emit_event(async_audit_repository(sa_conn), "person.merged", "person", 1, {})
        result = await sa_conn.execute(
            select(audit_log.c.id).where(audit_log.c.event_type == "person.merged")
        )
        assert result.first() is None

    async def test_default_payload_via_sa(self, sa_conn: AsyncConnection):
        token = set_current_user("admin")
        try:
            await async_emit_event(async_audit_repository(sa_conn), "person.rejected", "person", 99)
            result = await sa_conn.execute(
                select(audit_log.c.payload).order_by(audit_log.c.id.desc()).limit(1)
            )
            assert result.scalar_one() == {}
        finally:
            reset_current_user(token)
