"""Port : résolution des affiliations sur `source_authorships`.

Implémenté par `infrastructure.queries.pipeline.affiliations.PgAffiliationsQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class InPerimeterSyncCounts(NamedTuple):
    """Nombre de `source_authorships` dont `in_perimeter` a changé lors d'un alignement."""

    added: int  # passées à TRUE (entrées dans le périmètre)
    removed: int  # passées à FALSE (sorties du périmètre)


class AffiliationsQueries(Protocol):
    """Pose `in_perimeter` sur les `source_authorships` depuis leurs adresses résolues, et rafraîchit la matview qui l'alimente."""

    def sync_in_perimeter(
        self, conn: Connection, *, perimeter_ids: list[int]
    ) -> InPerimeterSyncCounts:
        """Aligne `in_perimeter` sur les structures `perimeter_ids`, lues depuis la matview, en n'écrivant que les changements."""
        ...

    def refresh_source_authorship_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `source_authorship_structures`, qui alimente `sync_in_perimeter`.

        À appeler après la matérialisation de `perimeter_structures` et la résolution des adresses, et avant le refresh de `authorship_structures`, qui en dérive.
        """
        ...
