"""Port : opérations sur la table `staging`.

Implémenté par `infrastructure.queries.pipeline.staging.PgStagingQueries`.
Partagé par tous les normalizers via `SourceNormalizer`.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Connection


@dataclass(frozen=True)
class StagingRow:
    """Projection commune de `staging` (4 colonnes) consommée par les normalizers wos, openalex, scanr, crossref, theses."""

    id: int
    source_id: str
    doi: str | None
    raw_data: dict[str, Any]


@dataclass(frozen=True)
class HalStagingRow(StagingRow):
    """`StagingRow` + la colonne `hal_collections` (TEXT[]) propre à HAL.

    Par substitution LSP : un `HalStagingRow` remplit le contrat de `StagingRow`. Le port retourne `list[StagingRow]` uniformément ; le normalizer HAL fait `isinstance(row, HalStagingRow)` pour accéder à `.hal_collections`.
    """

    hal_collections: list[str] | None


class StagingQueries(Protocol):
    """Opérations SQL sur la table `staging`.

    `fetch_pending_staging` / `fetch_staging_by_ids` retournent `list[StagingRow]` ; pour `source == 'hal'`, l'implémentation construit des `HalStagingRow` (sous-type de `StagingRow`) qui exposent en plus `.hal_collections`.
    """

    def reset_processed_flag(self, conn: Connection, source: str) -> int: ...

    def count_pending_staging(self, conn: Connection, source: str) -> int: ...

    def fetch_pending_staging(
        self, conn: Connection, source: str, *, limit: int
    ) -> list[StagingRow]: ...

    def fetch_pending_staging_ids(
        self, conn: Connection, source: str, *, limit: int
    ) -> list[int]: ...

    def fetch_staging_by_ids(
        self, conn: Connection, staging_ids: list[int], *, source: str
    ) -> list[StagingRow]: ...

    def mark_done(self, conn: Connection, staging_id: int) -> None: ...

    def fetch_existing_source_ids(self, conn: Connection, source: str) -> set[str]:
        """Set des `source_id` déjà présents en staging pour une source.

        Consommé par `SourceExtractor.run_as_phase` pour éviter de re-fetcher
        depuis l'API des documents déjà connus.
        """
        ...
