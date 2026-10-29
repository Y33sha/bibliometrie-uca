"""Modèles de réponse : lectures sur la table `config`."""

from typing import Any

from pydantic import BaseModel


class ConfigItem(BaseModel):
    """Ligne de la table `config` (paramètres applicatifs clé/valeur)."""

    key: str
    # `Any` plutôt que `JsonValue` : pydantic 2.12 génère pour `JsonValue`, récursif, des références circulaires (`JsonValue-Input`, `JsonValue-Output`). `openapi-typescript` les traduit en type autoréférent, que TypeScript refuse. La valeur JSONB reste libre côté API.
    value: Any
    description: str | None
