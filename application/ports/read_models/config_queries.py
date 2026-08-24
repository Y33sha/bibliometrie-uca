"""Port : lectures sur la table `config` (consommé par le router config).

Distinct du port `application.ports.repositories.config_repository.ConfigRepository`, qui en porte les écritures.

Implémenté par `infrastructure.read_models.config.PgConfigQueries`.
"""

from typing import Any, Protocol

from pydantic import BaseModel

from domain.config import is_secret_config_key


class ConfigItem(BaseModel):
    """Ligne de la table `config` (paramètres applicatifs clé/valeur).

    Pour une clé secrète (`SECRET_CONFIG_KEYS`), `value` reste `None` et `is_set` indique la présence d'un secret enregistré.
    """

    key: str
    # `Any` plutôt que `JsonValue` (récursif PEP 695) : le schéma JSON
    # généré par pydantic 2.12 contient des références circulaires
    # (`JsonValue-Input` / `JsonValue-Output`) que `openapi-typescript`
    # traduit en `components["schemas"]["JsonValue-Input"][]` self-ref,
    # ce que TypeScript refuse d'instancier. Frontière JSONB libre côté API.
    value: Any
    description: str | None
    is_set: bool = True

    @classmethod
    def from_stored(cls, key: str, value: Any, description: str | None) -> "ConfigItem":
        """Construit l'item depuis une ligne stockée, en masquant la valeur des clés secrètes."""
        is_set = value not in (None, "")
        if is_secret_config_key(key):
            return cls(key=key, value=None, description=description, is_set=is_set)
        return cls(key=key, value=value, description=description, is_set=is_set)


class ConfigQueries(Protocol):
    """Lectures pour /api/config/*."""

    def list_config(self, *, public_only: bool) -> list[ConfigItem]: ...

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]:
        """Clés dont la valeur désigne ce périmètre. Sert à refuser la suppression d'un périmètre encore cité."""
        ...
