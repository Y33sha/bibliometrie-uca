"""Query services pour les paramètres applicatifs (table `config`).

Lookups par clé pour l'application (extraction, OA email, etc.) restent
dans `infrastructure/app_config.py` ; ce module héberge les queries
servies par le router admin (listing complet, dérivation HAL) ainsi
que l'adapter du port `application.ports.config.ConfigStore`.
"""

import logging

from sqlalchemy import Connection, select, text, update

from application.ports.api.config_queries import ConfigItem, ConfigQueries
from application.ports.config import ConfigStore
from domain.types import JsonValue
from infrastructure.db.tables import config

logger = logging.getLogger(__name__)


class PgConfigQueries(ConfigQueries):
    """Adapter SA pour `application.ports.config_queries.ConfigQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_config(self) -> list[ConfigItem]:
        """Tous les paramètres applicatifs triés par clé."""
        result = self._conn.execute(
            select(config.c.key, config.c.value, config.c.description).order_by(config.c.key)
        )
        return [ConfigItem(key=r.key, value=r.value, description=r.description) for r in result]

    def get_hal_collections(self) -> dict[str, str]:
        """Collections HAL {code: label} dérivées des structures du périmètre.

        Lit `config.perimeter_extraction` (défaut "uca_wide"), résout les
        structures du périmètre, retourne leurs `hal_collection`. Fallback
        sur la clé `hal_collections` de la table config si aucune dérivation
        possible.
        """
        from infrastructure.queries.perimeter import get_perimeter_structure_ids

        try:
            perim_row = self._conn.execute(
                text("SELECT value #>> '{}' AS code FROM config WHERE key = :key"),
                {"key": "perimeter_extraction"},
            ).one_or_none()
            perim_code = perim_row.code if perim_row else None
            perim_code = perim_code or "uca_wide"

            perimeter_ids = get_perimeter_structure_ids(self._conn, perim_code)
            if perimeter_ids:
                rows = self._conn.execute(
                    text("""
                        SELECT hal_collection, COALESCE(acronym, name) AS label
                        FROM structures
                        WHERE id = ANY(:ids)
                          AND hal_collection IS NOT NULL
                          AND hal_collection != ''
                    """),
                    {"ids": list(perimeter_ids)},
                ).all()
                if rows:
                    return {r.hal_collection: r.label for r in rows}
        except Exception as e:
            logger.warning(f"Impossible de dériver les collections HAL depuis le périmètre : {e}")

        # Fallback : config.hal_collections (manuel)
        fallback_row = self._conn.execute(
            text("SELECT value FROM config WHERE key = :key"),
            {"key": "hal_collections"},
        ).one_or_none()
        if fallback_row and isinstance(fallback_row.value, dict):
            return fallback_row.value
        return {}


class PgConfig(ConfigStore):
    """Adapter SA pour `application.ports.config.ConfigStore`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def config_key_exists(self, key: str) -> bool:
        result = self._conn.execute(select(config.c.key).where(config.c.key == key))
        return result.first() is not None

    def update_config_value(self, key: str, value: JsonValue) -> dict:
        stmt = (
            update(config)
            .where(config.c.key == key)
            .values(value=value)
            .returning(config.c.key, config.c.value, config.c.description)
        )
        result = self._conn.execute(stmt)
        return dict(result.one()._mapping)

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        # Le `#>> '{}'` extrait le scalar JSON. SA Core n'a pas d'opérateur
        # direct ; on passe par text() avec bind nommé.
        result = self._conn.execute(
            text("SELECT key FROM config WHERE key LIKE 'perimeter_%' AND value #>> '{}' = :code"),
            {"code": perimeter_code},
        )
        return [r.key for r in result]
