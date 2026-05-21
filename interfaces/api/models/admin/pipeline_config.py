"""Modèles Pydantic (router-only) pour la config pipeline.

Le DTO `ConfigItem` (retourné par `ConfigQueries.list_config`) vit dans `application/ports/api/config_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4). Restent ici la réponse `HalCollectionsResponse` composée par le router (queries retourne un dict, le router ajoute `count`) et le body `ConfigValueUpdate`.
"""

from pydantic import BaseModel

from domain.types import JsonValue


class HalCollectionsResponse(BaseModel):
    """GET /api/config/hal-collections."""

    collections: dict[str, str]
    count: int


class ConfigValueUpdate(BaseModel):
    """Corps de PUT /api/config/{key} : value JSON-sérialisable arbitraire."""

    value: JsonValue
