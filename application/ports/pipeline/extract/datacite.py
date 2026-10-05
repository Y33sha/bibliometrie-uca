"""Port : adapter DataCite pour la phase extract.

Implémenté par `infrastructure.sources.datacite.extract_datacite.PgDataciteExtractAdapter`.

Regroupe en un seul Protocol la lecture de config (mots-clés d'affiliation), les appels HTTP à l'API DataCite et les écritures SQL dans `staging`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Connection

from application.ports.pipeline.extract._common import BatchInsertCounts
from domain.types import JsonValue


@dataclass(frozen=True)
class DataciteExtractConfig:
    """Config d'extraction DataCite chargée depuis la BDD : les mots-clés cherchés dans les affiliations des créateurs."""

    keywords: list[str]


@dataclass(frozen=True)
class DatacitePage:
    """Une page de résultats : ses nœuds, et l'URL de la page suivante (`None` en fin de résultats)."""

    records: list[Mapping[str, JsonValue]]
    next_url: str | None


class DataciteExtractAdapter(Protocol):
    """Port DataCite : config, HTTP, SQL."""

    def load_config(self, conn: Connection) -> DataciteExtractConfig: ...

    def get_years(self, conn: Connection, *, start_year: int | None = None) -> list[int]: ...

    def count(self, year: int, keywords: list[str]) -> int:
        """Nombre de DOI d'une année dont une affiliation de créateur contient l'un des mots-clés."""
        ...

    def fetch_page(self, year: int, keywords: list[str], next_url: str | None) -> DatacitePage:
        """Une page de résultats : la première quand `next_url` est `None`, sinon celle que désigne `next_url`."""
        ...

    def insert_batch(
        self, conn: Connection, records: list[Mapping[str, JsonValue]]
    ) -> BatchInsertCounts:
        """UPSERT staging d'une page de nœuds. Le commit est à la charge de l'appelant."""
        ...
