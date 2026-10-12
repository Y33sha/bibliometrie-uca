"""Port : recalcul, par le pipeline, du `pub_count` d'un éditeur, après une fusion d'éditeurs.

Implémenté par `pipeline.transformation.publishing.pub_counts.PubCountRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PubCountRecompute(Protocol):
    """Recalcul ciblé du `pub_count` d'un éditeur."""

    def refresh_publisher_pub_count(self, conn: Connection, publisher_id: int) -> None:
        """Recalcule le `pub_count` de l'éditeur, somme de celui de ses revues."""
        ...
