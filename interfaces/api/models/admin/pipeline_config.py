"""Modèles Pydantic (router-only) pour la config pipeline.

Le DTO `ConfigItem` (retourné par `ConfigQueries.list_config`) vit dans `application/ports/api/config_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4). Reste ici le body `ConfigValueUpdate`.
"""

from typing import Any

from pydantic import BaseModel


class ConfigValueUpdate(BaseModel):
    """Corps de PUT /api/config/{key} : value JSON-sérialisable arbitraire."""

    # `Any` plutôt que `JsonValue` (récursif PEP 695) : le schéma JSON
    # généré contient une self-référence que `openapi-typescript` n'arrive
    # pas à instancier côté TS (cf. `application/ports/api/config_queries.py`).
    value: Any
