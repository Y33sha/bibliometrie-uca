"""Port : lectures sur la config + dérivés (consommé par le router config).

Distinct du port `application.ports.config.ConfigStore` qui couvre la lecture/écriture par clé de la table `config`. Ce port-ci agrège les lectures qui dérivent des paramètres (ex: collections HAL des structures du périmètre) ou qui listent l'ensemble des paramètres.

Implémenté par `infrastructure.queries.config.PgConfigQueries`.

Co-localise le DTO `ConfigItem` (retourné par `list_config`). Cf. chantier `CODE_typage-projections-strict` Phase 4.
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel


class ConfigItem(BaseModel):
    """Ligne de la table `config` (paramètres applicatifs clé/valeur)."""

    key: str
    # `Any` plutôt que `JsonValue` : pydantic ne supporte pas l'alias récursif (RecursionError à la génération de schéma). Frontière JSONB libre côté API ; cas isolé documenté.
    value: Any
    description: str | None
    updated_at: datetime


class ConfigQueries(Protocol):
    """Lectures pour /api/config/*."""

    def list_config(self) -> list[ConfigItem]: ...

    def get_hal_collections(self) -> dict[str, str]: ...
