"""Port : opérations sur la table `staging`.

Implémenté par `infrastructure.queries.staging.PgStagingQueries`.
Partagé par tous les normalizers via `SourceNormalizer`.
"""

from typing import Any, NamedTuple, Protocol

from sqlalchemy import Connection, Row


class StagingRow(NamedTuple):
    """Projection des 4 colonnes communes de `staging` consommées par les normalizers (wos, openalex, scanr, crossref, theses)."""

    id: int
    source_id: str
    doi: str | None
    raw_data: dict[str, Any]


class HalStagingRow(NamedTuple):
    """Projection HAL : colonnes communes + `hal_collections` (text[]).

    HAL est la seule source qui consomme la colonne `staging.hal_collections` ; les autres normalizers passent par `StagingRow`.
    """

    id: int
    source_id: str
    doi: str | None
    raw_data: dict[str, Any]
    hal_collections: list[str] | None


class StagingQueries(Protocol):
    """Opérations SQL génériques sur la table `staging`."""

    def reset_processed_flag(self, conn: Connection, source: str) -> int: ...

    def count_pending_staging(self, conn: Connection, source: str) -> int: ...

    def fetch_pending_staging(
        self, conn: Connection, source: str, *, columns: str, limit: int
    ) -> list[Row[Any]]: ...

    def fetch_pending_staging_ids(
        self, conn: Connection, source: str, *, limit: int
    ) -> list[int]: ...

    def fetch_staging_by_ids(
        self, conn: Connection, staging_ids: list[int], *, columns: str
    ) -> list[Row[Any]]: ...

    def mark_done(self, conn: Connection, staging_id: int) -> None: ...
