"""Port : SQL de construction de la table `authorships`.

Implémenté par `infrastructure.queries.authorships_build.PgAuthorshipsBuildQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AuthorshipsBuildQueries(Protocol):
    """Opérations SQL pour promouvoir `source_authorships` → `authorships`."""

    def purge_authorships(self, conn: Connection) -> int: ...

    def insert_missing_authorships(self, conn: Connection) -> int: ...

    def link_source_authorships_to_authorship_for(self, conn: Connection, source: str) -> int: ...

    def propagate_author_position(self, conn: Connection) -> int: ...

    def propagate_is_corresponding(self, conn: Connection) -> int: ...

    def propagate_roles(self, conn: Connection) -> int: ...

    def reset_authorships_perimeter_and_structures(self, conn: Connection) -> int: ...

    def propagate_perimeter_and_structures_from(self, conn: Connection, source: str) -> int: ...

    def count_authorships_in_perimeter(self, conn: Connection) -> int: ...
