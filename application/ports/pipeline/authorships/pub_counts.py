"""Port : refresh des compteurs `pub_count` (journals + publishers), fin de phase authorships.

Implémenté par `infrastructure.queries.pipeline.authorships.pub_counts.PgPubCountsQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class PubCountChanges(NamedTuple):
    """Nombre de lignes dont le `pub_count` a effectivement changé lors d'un refresh."""

    journals: int
    publishers: int


class PubCountsQueries(Protocol):
    """Recalcul en masse des `pub_count` in-perimeter sur `journals` puis `publishers`."""

    def refresh_pub_counts(self, conn: Connection) -> PubCountChanges:
        """Recalcule tous les `pub_count`. Retourne le nombre de lignes changées de chaque côté (garde `IS DISTINCT FROM` : les lignes inchangées ne comptent pas)."""
        ...
