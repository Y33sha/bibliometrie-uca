"""Adapter PostgreSQL sync pour la table `config`."""

from sqlalchemy import Connection, text, update

from application.ports.repositories.config_repository import ConfigRepository
from domain.types import JsonValue
from infrastructure.db.tables import config


class PgConfigRepository(ConfigRepository):
    """Accès PostgreSQL sync à la table `config`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        # `#>> '{}'` extrait le scalaire JSON ; faute d'opérateur SA Core direct, on passe par text() avec un bind nommé.
        result = self._conn.execute(
            text("SELECT key FROM config WHERE key LIKE 'perimeter_%' AND value #>> '{}' = :code"),
            {"code": perimeter_code},
        )
        return [r.key for r in result]

    def update_config_value(self, key: str, value: JsonValue) -> dict[str, JsonValue] | None:
        stmt = (
            update(config)
            .where(config.c.key == key)
            .values(value=value)
            .returning(config.c.key, config.c.value, config.c.description)
        )
        row = self._conn.execute(stmt).one_or_none()
        return dict(row._mapping) if row is not None else None
