"""Écritures sur la table `config` (paramètres clé / valeur JSON)."""

from application.audit_log import emit_event
from application.ports.repositories.config_repository import ConfigRepository
from domain.config import normalize_config_value
from domain.errors import NotFoundError
from domain.types import JsonValue


class ConfigService:
    """Écritures sur les paramètres de configuration."""

    def __init__(self, *, config: ConfigRepository) -> None:
        self._config = config

    def update_config_value(self, key: str, value: JsonValue) -> dict[str, JsonValue]:
        """Met à jour la valeur d'un paramètre de configuration existant. Renvoie la ligne mise à jour.

        `value` est normalisée selon la clé (`normalize_config_value`), puis sérialisée en JSON.

        L'événement d'audit garde la trace du changement. La clé va dans la charge utile : `entity_id` accepte seulement un entier. La valeur précédente figure dans l'événement qui l'a posée.

        Raises:
            NotFoundError: clé introuvable.
        """
        normalisee = normalize_config_value(key, value)
        row = self._config.update_config_value(key, normalisee)
        if row is None:
            raise NotFoundError(f"Paramètre '{key}' introuvable")
        emit_event("config.updated", "config", None, {"key": key, "value": normalisee})
        return row
