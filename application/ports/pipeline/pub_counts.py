"""Port : refresh des compteurs `pub_count` (journals + publishers), fin de phase authorships.

Implémenté par `infrastructure.queries.pipeline.pub_counts.PgPubCountsQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PubCountsQueries(Protocol):
    """Recalcul en masse des `pub_count` in-perimeter sur `journals` puis `publishers`."""

    def refresh_pub_counts(self, conn: Connection) -> tuple[int, int]:
        """Recalcule tous les `pub_count`. Retourne `(lignes journals modifiées, publishers)`."""
        ...
