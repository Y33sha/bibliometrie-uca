"""Command handlers des écritures API sur la table `config` : frontière transactionnelle.

Écriture triviale, servie par le port `ConfigRepository` sans brique agnostique séparée.
"""

from sqlalchemy import Connection

from application.ports.repositories.config_repository import ConfigRepository
from domain.errors import NotFoundError
from domain.types import JsonValue


def update_config_value(
    conn: Connection,
    key: str,
    value: JsonValue,
    *,
    config: ConfigRepository,
) -> dict[str, JsonValue]:
    """Met à jour la valeur d'un paramètre de config existant. `value` est sérialisé en JSON. Retourne la ligne mise à jour ; lève `NotFoundError` si la clé n'existe pas."""
    row = config.update_config_value(key, value)
    if row is None:
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    conn.commit()
    return row
