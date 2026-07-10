"""
Service Config — orchestrateur des écritures sur la table `config` (clé / valeur JSON).

Le SQL vit dans `infrastructure/queries/config.py`. Les routers passent par ces fonctions pour toute écriture ; les lectures restent autorisées dans les routers (convention du projet). L'agrégat Perimeter, historiquement servi ici, a son propre package `application/perimeters/`.
"""

from application.ports.config import ConfigStore
from domain.errors import NotFoundError
from domain.types import JsonValue


def update_config_value(key: str, value: JsonValue, *, config: ConfigStore) -> dict[str, JsonValue]:
    """Met à jour la valeur d'un paramètre de config existant.

    `value` est sérialisé en JSON. Retourne la ligne mise à jour.
    Lève NotFoundError si la clé n'existe pas.
    """
    if not config.config_key_exists(key):
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    return config.update_config_value(key, value)
