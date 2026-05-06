"""Port : opérations sur la table `config` (clé/valeur applicative).

`config` n'est pas un agrégat métier — c'est un store clé/valeur utilisé
par l'orchestration (paramètres pipeline, identifiants sources, etc.).
Le port vit donc dans `application/ports/` plutôt que dans `domain/ports/`.

Implémenté par `infrastructure.db.queries.config.PgAsyncConfig`.
"""

from typing import Any, Protocol


class AsyncConfigStore(Protocol):
    """Lecture/écriture des paramètres applicatifs (table `config`)."""

    async def config_key_exists(self, key: str) -> bool: ...

    async def update_config_value(self, key: str, value: Any) -> dict: ...

    async def config_keys_referencing_perimeter(self, perimeter_code: str) -> list[str]: ...
