"""Modèles de réponse : lectures sur la table `config`."""

from typing import Any

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
