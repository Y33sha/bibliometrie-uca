"""Modèles de réponse : lectures sur la table `config`."""

from typing import Any

from application.ports.model import Model


class ConfigItem(Model):
    """Ligne de la table `config` (paramètres applicatifs clé/valeur)."""

    key: str
    value: Any
    """Valeur JSONB, libre côté API. Avec `JsonValue`, `openapi-typescript` produit un type autoréférent, refusé par TypeScript."""
    description: str | None
    minimum: int | None = None
    """Borne inférieure incluse d'une clé entière."""
    maximum: int | None = None
    """Borne supérieure incluse d'une clé entière."""
    value_if_null: int | None = None
    """Valeur appliquée quand `value` est nulle : première année moissonnée sans année fixée."""
