"""Port ConfigRepository — écritures sur la table `config` (paramètres applicatifs clé/valeur).

Sert l'admin qui édite les paramètres. Les lookups par clé du pipeline vivent dans `pipeline/runtime/config.py`, hors de ce port.
"""

from typing import Protocol

from domain.types import JsonValue


class ConfigRepository(Protocol):
    """Mise à jour d'un paramètre applicatif."""

    def update_config_value(self, key: str, value: JsonValue) -> dict[str, JsonValue] | None:
        """Met à jour la valeur d'un paramètre. Retourne la ligne `{key, value, description}`, ou `None` si la clé n'existe pas."""
        ...
