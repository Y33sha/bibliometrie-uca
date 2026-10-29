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
        """Met à jour la valeur d'un paramètre de config existant. `value` est ramené à la forme que la clé impose (`normalize_config_value`) puis sérialisé en JSON. Renvoie la ligne mise à jour ; lève `NotFoundError` si la clé n'existe pas.

        Un réglage change le comportement de l'application sans trace dans les données : l'événement d'audit garde le changement. La clé, un texte, va dans la charge utile : l'identifiant d'agrégat est un entier. La valeur précédente est absente : le journal la contient déjà, dans l'événement qui l'a posée.
        """
        normalisee = normalize_config_value(key, value)
        row = self._config.update_config_value(key, normalisee)
        if row is None:
            raise NotFoundError(f"Paramètre '{key}' introuvable")
        emit_event("config.updated", "config", None, {"key": key, "value": normalisee})
        return row
