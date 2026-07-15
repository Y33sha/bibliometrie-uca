"""Port : opérations sur la table `config` (clé/valeur applicative).

`config` n'est pas un agrégat métier — c'est un store clé/valeur utilisé
par l'orchestration (paramètres pipeline, identifiants sources, etc.).
Le port vit donc à la racine de `application/ports/` plutôt que dans
`application/ports/repositories/` (réservé aux agrégats du domaine).

Implémenté par `infrastructure.queries.config.PgConfig`.
"""

from typing import Protocol

from domain.types import JsonValue


class ConfigStore(Protocol):
    """Lecture/écriture des paramètres applicatifs (table `config`)."""

    def update_config_value(self, key: str, value: JsonValue) -> dict[str, JsonValue] | None:
        """Met à jour la valeur d'un paramètre. Retourne la ligne `{key, value, description}`, ou `None` si la clé n'existe pas."""
        ...

    def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]: ...
