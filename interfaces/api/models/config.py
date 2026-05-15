"""Modèles Pydantic pour la table de config (paramètres applicatifs clé/valeur)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ConfigItem(BaseModel):
    """Ligne de la table `config` (paramètres applicatifs clé/valeur)."""

    key: str
    # `Any` plutôt que `JsonValue` : pydantic ne supporte pas l'alias
    # récursif (RecursionError à la génération de schéma). Frontière
    # JSONB libre côté API ; cas isolé documenté.
    value: Any
    description: str | None
    updated_at: datetime


class HalCollectionsResponse(BaseModel):
    """GET /api/config/hal-collections."""

    collections: dict[str, str]
    count: int


class ConfigValueUpdate(BaseModel):
    """Corps de PUT /api/config/{key} : value JSON-sérialisable arbitraire."""

    # cf. `ConfigItem.value` — pydantic ne supporte pas l'alias récursif.
    value: Any
