"""Modèles Pydantic du router de configuration : corps des requêtes entrantes."""

from typing import Any

from pydantic import BaseModel


class ConfigValueUpdate(BaseModel):
    """Corps de PUT /api/config/{key} : une valeur JSON quelconque."""

    # `Any` plutôt que `JsonValue` : openapi-typescript traduit le schéma autoréférent de `JsonValue` en un type que TypeScript refuse (`infrastructure/read_models/config/models.py`).
    value: Any
