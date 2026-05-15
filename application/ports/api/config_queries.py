"""Port : lectures sur la config + dérivés (consommé par le router config).

Distinct du port `application.ports.config.ConfigStore` qui couvre la
lecture/écriture par clé de la table `config`. Ce port-ci agrège les
lectures qui dérivent des paramètres (ex: collections HAL des
structures du périmètre) ou qui listent l'ensemble des paramètres.

Implémenté par `infrastructure.queries.config.PgConfigQueries`.
"""

from typing import Any, Protocol


class ConfigQueries(Protocol):
    """Lectures pour /api/config/*."""

    def list_config(self) -> list[dict[str, Any]]: ...

    def get_hal_collections(self) -> dict[str, str]: ...
