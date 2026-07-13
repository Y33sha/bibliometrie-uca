"""Port : recompute du cache `addresses.pub_count`, fin de phase publications.

Implémenté par `infrastructure.queries.pipeline.address_pub_count.PgAddressPubCountQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AddressPubCountQueries(Protocol):
    """Recalcul du nombre de publications distinctes rattachées à chaque adresse."""

    def recompute_pub_count(self, conn: Connection) -> int:
        """Recompute `addresses.pub_count` sur toutes les adresses. Retourne le nombre de lignes modifiées."""
        ...
