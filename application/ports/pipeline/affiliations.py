"""Port : résolution des affiliations sur `source_authorships`.

Implémenté par `infrastructure.db.queries.affiliations.PgAffiliationsQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AffiliationsQueries(Protocol):
    """Opérations SQL pour poser `in_perimeter`/`structure_ids` via adresses résolues."""

    def reset_source_authorships_for(self, conn: Connection, source: str) -> int: ...

    def set_in_perimeter_from_addresses(
        self, conn: Connection, *, source: str, perimeter_ids: list[int], daily: bool
    ) -> int: ...

    def set_structure_ids_from_addresses(
        self, conn: Connection, *, source: str, wide_ids: list[int], daily: bool
    ) -> int: ...

    def set_theses_structure_ids(
        self, conn: Connection, *, wide_ids: list[int], daily: bool
    ) -> int: ...

    def count_source_authorships_stats(
        self, conn: Connection, source: str
    ) -> tuple[int, int, int]: ...
