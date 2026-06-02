"""Port : SQL de construction de la table `authorships`.

Implémenté par `infrastructure.queries.authorships_build.PgAuthorshipsBuildQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AuthorshipsBuildQueries(Protocol):
    """Opérations SQL pour promouvoir `source_authorships` → `authorships`."""

    def purge_authorships(self, conn: Connection) -> int: ...

    def insert_missing_authorships(self, conn: Connection) -> int: ...

    def analyze_authorships(self, conn: Connection) -> None:
        """Met à jour les stats Postgres sur `authorships`.

        À appeler après une INSERT massive (typiquement `insert_missing_authorships` en mode rebuild_full) pour que les planners SQL des étapes suivantes (`propagate_is_corresponding`, `propagate_roles`) aient des estimations correctes. Sans ça, Postgres garde des stats périmées (`null_frac = 0` sur les colonnes fraîchement insérées) et choisit un Nested Loop O(n×m) au lieu d'un Hash Join, ce qui peut bloquer indéfiniment sur ~100k authorships.
        """
        ...

    def link_source_authorships_to_authorship_for(self, conn: Connection, source: str) -> int: ...

    def propagate_author_position(self, conn: Connection) -> int: ...

    def propagate_is_corresponding(self, conn: Connection) -> int: ...

    def propagate_roles(self, conn: Connection) -> int: ...

    def reset_authorships_perimeter(self, conn: Connection) -> int: ...

    def propagate_perimeter_from(self, conn: Connection, source: str) -> int: ...

    def refresh_authorship_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `authorship_structures` (`REFRESH … CONCURRENTLY`)."""
        ...

    def count_authorships_in_perimeter(self, conn: Connection) -> int: ...
