"""Adapter PostgreSQL sync pour la table `config`."""

from sqlalchemy import Connection, update

from domain.types import JsonValue
from infrastructure.db.tables import config


class PgConfigRepository:
    """Accès PostgreSQL sync à la table `config`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def update_config_value(self, key: str, value: JsonValue) -> dict[str, JsonValue] | None:
        stmt = (
            update(config)
            .where(config.c.key == key)
            .values(value=value)
            .returning(config.c.key, config.c.value, config.c.description)
        )
        row = self._conn.execute(stmt).one_or_none()
        return dict(row._mapping) if row is not None else None
