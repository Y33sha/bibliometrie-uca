"""Port : résolution des affiliations sur `source_authorships`.

Implémenté par `infrastructure.queries.pipeline.affiliations.PgAffiliationsQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AffiliationsQueries(Protocol):
    """Opérations SQL pour poser `in_perimeter`/`structure_ids` via adresses résolues."""

    def reset_source_authorships_for(self, conn: Connection, source: str) -> int: ...

    def set_in_perimeter_from_addresses(
        self, conn: Connection, *, source: str, perimeter_ids: list[int], daily: bool
    ) -> int: ...

    def refresh_source_authorship_structures(self, conn: Connection) -> None: ...

    def count_source_authorships_stats(
        self, conn: Connection, source: str
    ) -> tuple[int, int, int]: ...
