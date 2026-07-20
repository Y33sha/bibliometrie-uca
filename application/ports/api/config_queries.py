"""Port : lectures sur la table `config` (consommé par le router config).

Distinct du port `application.ports.config.ConfigStore`, qui en porte les écritures.

Implémenté par `infrastructure.queries.config.PgConfigQueries`.
"""

from typing import Any, Protocol

from pydantic import BaseModel


class ConfigItem(BaseModel):
    """Ligne de la table `config` (paramètres applicatifs clé/valeur)."""

    key: str
    # `Any` plutôt que `JsonValue` (récursif PEP 695) : le schéma JSON
    # généré par pydantic 2.12 contient des références circulaires
    # (`JsonValue-Input` / `JsonValue-Output`) que `openapi-typescript`
    # traduit en `components["schemas"]["JsonValue-Input"][]` self-ref,
    # ce que TypeScript refuse d'instancier. Frontière JSONB libre côté API.
    value: Any
    description: str | None


class ConfigQueries(Protocol):
    """Lectures pour /api/config/*."""

    def list_config(self, *, public_only: bool) -> list[ConfigItem]: ...

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        """Clés dont la valeur désigne ce périmètre. Sert à refuser la suppression d'un périmètre encore cité."""
        ...
