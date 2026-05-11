"""Port : opérations sur la table `staging`.

Implémenté par `infrastructure.db.queries.staging.PgStagingQueries`.
Partagé par tous les normalizers via `SourceNormalizer`.
"""

from typing import Any, Protocol

from sqlalchemy import Connection


class StagingQueries(Protocol):
    """Opérations SQL génériques sur la table `staging`."""

    def reset_processed_flag(self, conn: Connection, source: str) -> int: ...

    def count_pending_staging(self, conn: Connection, source: str) -> int: ...

    def fetch_pending_staging(
        self, conn: Connection, source: str, *, columns: str, limit: int
    ) -> list[Any]: ...

    def fetch_pending_staging_ids(
        self, conn: Connection, source: str, *, limit: int
    ) -> list[int]: ...

    def fetch_staging_by_ids(
        self, conn: Connection, staging_ids: list[int], *, columns: str
    ) -> list[Any]: ...

    def mark_done(self, conn: Connection, staging_id: int) -> None: ...
