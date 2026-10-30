"""Modèles de réponse : lectures sur la table `config`."""

from typing import Any

from pydantic import BaseModel


class ConfigItem(BaseModel):
    """Ligne de la table `config` (paramètres applicatifs clé/valeur)."""

    key: str
    value: Any
    """Valeur JSONB, libre côté API. Avec `JsonValue`, `openapi-typescript` produit un type autoréférent, refusé par TypeScript."""
    description: str | None
