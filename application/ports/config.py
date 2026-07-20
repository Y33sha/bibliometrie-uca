"""Port : écritures sur la table `config` (paramètres applicatifs clé/valeur).

Sert l'admin qui édite les paramètres. Les lookups par clé du pipeline et des CLI (clé d'API OpenAlex, email du polite pool, URLs de base) vivent dans `infrastructure/sources/config.py` : ils sont lus au composition root et passés en paramètres, sans passer par ce port.

`config` n'est pas un agrégat du domaine ; le port vit à la racine de `application/ports/`, hors de `repositories/` (agrégats), `api/` (projections de lecture des routers) et `pipeline/` (queries de phase).

Implémenté par `infrastructure.queries.config.PgConfig`.
"""

from typing import Protocol

from domain.types import JsonValue


class ConfigStore(Protocol):
    """Mise à jour d'un paramètre applicatif."""

    def update_config_value(self, key: str, value: JsonValue) -> dict[str, JsonValue] | None:
        """Met à jour la valeur d'un paramètre. Retourne la ligne `{key, value, description}`, ou `None` si la clé n'existe pas."""
        ...
