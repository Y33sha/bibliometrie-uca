"""Query services pour les paramètres applicatifs (table `config`).

Ce module sert la couche requêtes-API : `PgConfigQueries` rend au router admin le listing complet et les clés qui référencent un périmètre. L'écriture d'une valeur vit dans `infrastructure/repositories/config_repository.py`. Les lookups par clé du pipeline — années, collections HAL, comptes de service des sources — vivent à part, dans `infrastructure/sources/config.py`.
"""

from sqlalchemy import Connection, select, text

from application.ports.api.config_queries import ConfigItem, ConfigQueries
from domain.config import PUBLIC_CONFIG_KEYS
from infrastructure.db.tables import config


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
        # `#>> '{}'` extrait le scalaire JSON ; faute d'opérateur SA Core direct, on passe par text() avec un bind nommé.
        result = self._conn.execute(
            text("SELECT key FROM config WHERE key LIKE 'perimeter_%' AND value #>> '{}' = :code"),
            {"code": perimeter_code},
        )
        return [r.key for r in result]
