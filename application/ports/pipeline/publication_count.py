"""Port : recalcul, par le pipeline, du `publication_count` d'un éditeur, après une fusion d'éditeurs.

Implémenté par `pipeline.transformation.publishing.publication_counts.PubCountRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PubCountRecompute(Protocol):
    """Recalcul ciblé du `publication_count` d'un éditeur."""

    def refresh_publisher_publication_count(self, conn: Connection, publisher_id: int) -> None:
        """Recalcule le `publication_count` de l'éditeur, somme de celui de ses revues."""
        ...
