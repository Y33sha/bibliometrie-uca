"""Port ConfigRepository : écritures sur la table `config` (paramètres applicatifs), et lectures qui les conditionnent, pour l'administration.

Les lectures par clé du pipeline sont définies dans `pipeline/runtime/config.py`.
"""

from typing import Protocol

from domain.types import JsonValue


class ConfigRepository(Protocol):
    """Mise à jour d'un paramètre applicatif."""

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        """Renvoie les clés de configuration désignant ce périmètre."""
        ...

    def update_config_value(self, key: str, value: JsonValue) -> dict[str, JsonValue] | None:
        """Met à jour la valeur d'un paramètre. Renvoie la ligne `{key, value, description}`, ou `None` si la clé n'existe pas."""
        ...
