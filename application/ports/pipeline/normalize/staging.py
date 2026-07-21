"""Port : opérations sur la table `staging`.

Implémenté par `infrastructure.queries.pipeline.normalize.staging.PgStagingQueries`.
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

    def count_pending_staging(self, conn: Connection, source: str) -> int:
        """Nombre de lignes `staging` non traitées (`processed = FALSE`) pour la source."""
        ...

    def fetch_pending_staging(
        self, conn: Connection, source: str, *, limit: int
    ) -> list[StagingRow]:
        """Les `limit` premières lignes non traitées de la source, par `id` croissant."""
        ...

    def fetch_pending_staging_ids(self, conn: Connection, source: str) -> list[int]:
        """Les `id` de toutes les lignes non traitées de la source — pour un fetch par sous-lots."""
        ...

    def fetch_staging_by_ids(
        self, conn: Connection, staging_ids: list[int], *, source: str
    ) -> list[StagingRow]:
        """Les lignes `staging` dont l'`id` figure dans la liste donnée."""
        ...

    def mark_done(self, conn: Connection, staging_id: int) -> None:
        """Marque une ligne traitée (`processed = TRUE`) et vide son `raw_data` ; l'adapter en archive le payload au raw store au préalable."""
        ...
