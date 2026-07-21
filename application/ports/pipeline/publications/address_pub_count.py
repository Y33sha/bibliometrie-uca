"""Port : recalcul du cache `addresses.pub_count`, en fin de phase publications.

Implémenté par `infrastructure.queries.pipeline.publications.address_pub_count.PgAddressPubCountQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AddressPubCountQueries(Protocol):
    """Recalcul du nombre de publications distinctes rattachées à chaque adresse."""

    def recompute_pub_count(self, conn: Connection) -> int:
        """Recalcule `addresses.pub_count` sur **toutes** les adresses, depuis les publications canoniques liées par `source_authorship_addresses`. Retourne le nombre de lignes modifiées.

        Idempotent, et de portée globale : une adresse qui a perdu tous ses liens repasse à 0.
        """
        ...
