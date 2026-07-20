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
from domain.config import PUBLIC_CONFIG_KEYS
from domain.types import JsonValue
from infrastructure.db.tables import config

logger = logging.getLogger(__name__)


def laboratory_structure_types(conn: Connection) -> list[str]:
    """Types de structure que la configuration tient pour des laboratoires.

    Rend `["labo"]` à défaut de configuration : c'est le type qui porte le mot.
    """
    row = conn.execute(
        text("SELECT value FROM config WHERE key = 'laboratories_display_types'")
    ).one_or_none()
    value = row.value if row else None
    return [str(v) for v in value] if isinstance(value, list) and value else ["labo"]


class PgConfigQueries(ConfigQueries):
    """Adapter SA pour `application.ports.api.config_queries.ConfigQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_config(self, *, public_only: bool) -> list[ConfigItem]:
        """Paramètres applicatifs triés par clé.

        `public_only` restreint à `PUBLIC_CONFIG_KEYS` : la table porte aussi les clés d'API et les comptes de service des sources, qu'une lecture sans session ne doit pas rendre.
        """
        stmt = select(config.c.key, config.c.value, config.c.description).order_by(config.c.key)
        if public_only:
            stmt = stmt.where(config.c.key.in_(PUBLIC_CONFIG_KEYS))
        return [
            ConfigItem(key=r.key, value=r.value, description=r.description)
            for r in self._conn.execute(stmt)
        ]

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        """Clés dont la valeur désigne ce périmètre."""
        # Le `#>> '{}'` extrait le scalaire JSON. SA Core n'a pas d'opérateur direct ;
        # on passe par text() avec bind nommé.
        result = self._conn.execute(
            text("SELECT key FROM config WHERE key LIKE 'perimeter_%' AND value #>> '{}' = :code"),
            {"code": perimeter_code},
        )
        return [r.key for r in result]


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
