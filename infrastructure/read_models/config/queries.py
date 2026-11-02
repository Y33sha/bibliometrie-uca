"""Lectures des paramètres applicatifs (table `config`), pour l'administration.

`infrastructure/repositories/config_repository.py` écrit les valeurs. `pipeline/runtime/config.py` contient les lectures par clé du pipeline (années, plafonds, délais).
"""

from sqlalchemy import Connection, select

from domain.config import PUBLIC_CONFIG_KEYS, SETTINGS, ConfigKey, start_year_value
from domain.dates import today
from domain.types import JsonValue
from infrastructure.db.tables import config
from infrastructure.read_models.config.models import (
    ConfigItem,
)


def config_item(key: str, value: JsonValue, description: str | None) -> ConfigItem:
    """Construit la ligne de `config` avec les règles de sa clé : bornes d'une clé entière, valeur appliquée à une valeur nulle. Une clé inconnue du domaine est sans règle."""
    setting = SETTINGS[ConfigKey(key)] if key in ConfigKey else None
    minimum, maximum = (setting.bounds if setting else None) or (None, None)
    value_if_null = (
        start_year_value(None, today().year) if key == ConfigKey.PIPELINE_START_YEAR_FULL else None
    )
    return ConfigItem(
        key=key,
        value=value,
        description=description,
        minimum=minimum,
        maximum=maximum,
        value_if_null=value_if_null,
    )


class ConfigQueries:
    """Lectures sur la table `config`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_config(self, *, public_only: bool) -> list[ConfigItem]:
        """Renvoie les paramètres applicatifs triés par clé.

        Args:
            public_only: restreint à la liste blanche `PUBLIC_CONFIG_KEYS` ; les autres clés sont réservées à une session.
        """
        stmt = select(config.c.key, config.c.value, config.c.description).order_by(config.c.key)
        if public_only:
            stmt = stmt.where(config.c.key.in_(PUBLIC_CONFIG_KEYS))
        return [config_item(r.key, r.value, r.description) for r in self._conn.execute(stmt)]
