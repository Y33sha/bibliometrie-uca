"""Écritures API sur la table `config` (clé / valeur JSON) : command handlers.

Une écriture API est une commande (intention courte d'un acteur). Le handler reçoit la connexion de la requête, applique la règle métier et `conn.commit()` au succès, pour que la donnée soit persistée avant l'envoi de la réponse. Le SQL vit dans `infrastructure/queries/config.py` (port `ConfigStore`) ; les lectures restent autorisées dans les routers (convention du projet).
"""

from sqlalchemy import Connection

from application.ports.config import ConfigStore
from domain.errors import NotFoundError
from domain.types import JsonValue


def update_config_value(
    conn: Connection,
    key: str,
    value: JsonValue,
    *,
    config: ConfigStore,
) -> dict[str, JsonValue]:
    """Met à jour la valeur d'un paramètre de config existant. `value` est sérialisé en JSON. Retourne la ligne mise à jour ; lève `NotFoundError` si la clé n'existe pas."""
    if not config.config_key_exists(key):
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    row = config.update_config_value(key, value)
    conn.commit()
    return row
