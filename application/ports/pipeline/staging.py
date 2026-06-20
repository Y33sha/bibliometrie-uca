"""Port : opérations sur la table `staging`.

Implémenté par `infrastructure.queries.pipeline.staging.PgStagingQueries`.
Partagé par tous les normalizers via `SourceNormalizer`.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Connection


@dataclass(frozen=True)
class StagingRow:
    """Projection commune de `staging` (4 colonnes) consommée par tous les normalizers."""

    id: int
    source_id: str
    doi: str | None
    raw_data: dict[str, Any]


class StagingQueries(Protocol):
    """Opérations SQL sur la table `staging`."""

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
