"""Port : lectures sur la config + dérivés (consommé par le router config).

Distinct du port `application.ports.config.AsyncConfigStore` qui couvre
la lecture/écriture par clé de la table `config`. Ce port-ci agrège
les lectures qui dérivent des paramètres (ex: collections HAL des
structures du périmètre) ou qui listent l'ensemble des paramètres.

Implémenté par
`infrastructure.db.queries.config.PgAsyncConfigQueries`.
"""

from typing import Any, Protocol


class AsyncConfigQueries(Protocol):
    """Lectures async pour /api/config/*."""

    async def list_config(self) -> list[dict[str, Any]]: ...

    async def get_hal_collections(self) -> dict[str, str]: ...
