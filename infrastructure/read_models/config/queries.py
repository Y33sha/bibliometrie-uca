"""Lectures des paramètres applicatifs (table `config`), pour l'administration.

`infrastructure/repositories/config_repository.py` écrit les valeurs. `pipeline/runtime/config.py` contient les lectures par clé du pipeline (années, plafonds, délais).
"""

from sqlalchemy import Connection, select

from domain.config import PUBLIC_CONFIG_KEYS
from infrastructure.db.tables import config
from infrastructure.read_models.config.models import (
    ConfigItem,
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
        return [
            ConfigItem(key=r.key, value=r.value, description=r.description)
            for r in self._conn.execute(stmt)
        ]
