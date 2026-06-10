"""Port : résolution des affiliations sur `source_authorships`.

Implémenté par `infrastructure.queries.pipeline.affiliations.PgAffiliationsQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AffiliationsQueries(Protocol):
    """Opérations SQL pour poser `in_perimeter`/`structure_ids` via adresses résolues."""

    def sync_in_perimeter(self, conn: Connection, *, perimeter_ids: list[int]) -> tuple[int, int]:
        """Aligne `in_perimeter` sur le périmètre (depuis la matview), n'écrivant que les changements.

        Retourne `(passées_TRUE, passées_FALSE)`.
        """
        ...

    def refresh_source_authorship_structures(self, conn: Connection) -> None: ...

    def count_source_authorships_stats(
        self, conn: Connection, source: str
    ) -> tuple[int, int, int]: ...
