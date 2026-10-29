"""Adapter PostgreSQL sync des utilisateurs et de leurs rôles."""

from collections.abc import Iterable

from sqlalchemy import Connection, delete, select
from sqlalchemy.dialects.postgresql import insert

from application.ports.repositories.user_repository import UserRepository
from infrastructure.db.tables import user_roles, users


class PgUserRepository(UserRepository):
    """Accès PostgreSQL sync à `ops.users` et `ops.user_roles`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def roles_of(self, login: str) -> frozenset[str] | None:
        rows = self._conn.execute(
            select(users.c.id, user_roles.c.role_code)
            .select_from(users.outerjoin(user_roles, user_roles.c.user_id == users.c.id))
            .where(users.c.login == login)
        ).all()
        if not rows:
            return None
        return frozenset(row.role_code for row in rows if row.role_code is not None)

    def ensure_user(self, login: str, roles: Iterable[str]) -> None:
        self._conn.execute(insert(users).values(login=login).on_conflict_do_nothing())
        user_id = self._conn.execute(select(users.c.id).where(users.c.login == login)).scalar_one()
        for role in roles:
            self._conn.execute(
                insert(user_roles).values(user_id=user_id, role_code=role).on_conflict_do_nothing()
            )

    def list_users(self) -> list[tuple[str, frozenset[str]]]:
        """Utilisateurs triés par login, avec leurs rôles."""
        rows = self._conn.execute(
            select(users.c.login, user_roles.c.role_code)
            .select_from(users.outerjoin(user_roles, user_roles.c.user_id == users.c.id))
            .order_by(users.c.login)
        ).all()
        by_login: dict[str, set[str]] = {}
        for row in rows:
            roles = by_login.setdefault(row.login, set())
            if row.role_code is not None:
                roles.add(row.role_code)
        return [(login, frozenset(roles)) for login, roles in by_login.items()]

    def revoke(self, login: str, roles: Iterable[str]) -> None:
        """Retire des rôles à un utilisateur."""
        user_id = select(users.c.id).where(users.c.login == login).scalar_subquery()
        self._conn.execute(
            delete(user_roles).where(
                user_roles.c.user_id == user_id, user_roles.c.role_code.in_(list(roles))
            )
        )

    def remove_user(self, login: str) -> bool:
        """Supprime un utilisateur et ses rôles. Rend `False` s'il était absent."""
        return bool(self._conn.execute(delete(users).where(users.c.login == login)).rowcount)
