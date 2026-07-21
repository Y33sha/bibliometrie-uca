"""Port : purge des publications orphelines (fin de phase authorships).

Implémenté par `infrastructure.queries.pipeline.authorships.purge_orphan_publications.PgPurgeOrphanPublicationsQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PurgeOrphanPublicationsQueries(Protocol):
    """Suppression des publications sans authorship."""

    def purge_orphan_publications(self, conn: Connection, *, limit: int | None = None) -> int:
        """Supprime les publications sans aucun authorship (un chunk si `limit`).

        Retourne le nombre supprimé. Le batching (boucle + commit par chunk) est piloté par l'orchestrateur de phase.
        """
        ...
