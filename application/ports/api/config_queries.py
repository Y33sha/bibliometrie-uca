"""Port : lectures sur la config + dérivés (consommé par le router config).

Distinct du port `application.ports.config.ConfigStore`, qui porte les écritures sur la table `config`. Ce port-ci liste l'ensemble des paramètres.

Implémenté par `infrastructure.queries.config.PgConfigQueries`.

Co-localise le DTO `ConfigItem` (retourné par `list_config`). Cf. chantier `CODE_typage-projections-strict` Phase 4.
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

    def list_config(self) -> list[ConfigItem]: ...
