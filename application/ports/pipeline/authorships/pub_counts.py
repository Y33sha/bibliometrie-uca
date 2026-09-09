"""Port : refresh des compteurs `pub_count` des revues puis des éditeurs, fin de phase authorships.

Implémenté par `infrastructure.pipeline.authorships.pub_counts.PgPubCountsQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PubCountsQueries(Protocol):
    """Recalcul en masse des `pub_count` in-perimeter sur `journals` puis `publishers`."""

    def refresh_journal_pub_counts(self, conn: Connection) -> int:
        """Recalcule le `pub_count` de chaque revue.

        Rend le nombre de lignes changées (garde `IS DISTINCT FROM` : les lignes inchangées ne comptent pas).
        """
        ...

    def refresh_publisher_pub_counts(self, conn: Connection) -> int:
        """Recalcule le `pub_count` de chaque éditeur, somme de celui de ses revues.

        À appeler après `refresh_journal_pub_counts`, dont il lit le résultat. Rend le nombre de lignes changées.
        """
        ...
