"""Query services pour les paramètres applicatifs (table `config`).

Lookups par clé pour l'application (extraction, OA email, etc.) restent
dans `infrastructure/sources/config.py` ; ce module héberge la query servie
par le router admin (listing complet) ainsi que l'adapter du port
`application.ports.config.ConfigStore`.
"""

import logging

from sqlalchemy import Connection, select, text, update

from application.ports.api.config_queries import ConfigItem, ConfigQueries
from application.ports.config import ConfigStore
from domain.types import JsonValue
from infrastructure.db.tables import config

logger = logging.getLogger(__name__)


class PgConfigQueries(ConfigQueries):
    """Adapter SA pour `application.ports.api.config_queries.ConfigQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_config(self) -> list[ConfigItem]:
        """Tous les paramètres applicatifs triés par clé."""
        result = self._conn.execute(
            select(config.c.key, config.c.value, config.c.description).order_by(config.c.key)
        )
        return [ConfigItem(key=r.key, value=r.value, description=r.description) for r in result]


class PgConfig(ConfigStore):
    """Adapter SA pour `application.ports.config.ConfigStore`."""

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

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        # Le `#>> '{}'` extrait le scalar JSON. SA Core n'a pas d'opérateur
        # direct ; on passe par text() avec bind nommé.
        result = self._conn.execute(
            text("SELECT key FROM config WHERE key LIKE 'perimeter_%' AND value #>> '{}' = :code"),
            {"code": perimeter_code},
        )
        return [r.key for r in result]
