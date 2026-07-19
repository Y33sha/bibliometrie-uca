"""Port : lectures sur la config + dérivés (consommé par le router config).

Distinct du port `application.ports.config.ConfigStore`, qui porte les écritures sur la table `config`. Ce port-ci liste l'ensemble des paramètres.

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


# Clés que la lecture publique de la configuration rend. Liste blanche : une clé qu'on
# n'y inscrit pas reste réservée à une session, ce qui protège par défaut les clés
# d'API et les comptes de service que la table porte aussi.
PUBLIC_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "api_base_urls",
        "hal_portals",
        "laboratories_display_types",
        "perimeter_extraction",
        "perimeter_persons",
        "pipeline_start_year_full",
    }
)


class ConfigQueries(Protocol):
    """Lectures pour /api/config/*."""

    def list_config(self, *, public_only: bool) -> list[ConfigItem]: ...
