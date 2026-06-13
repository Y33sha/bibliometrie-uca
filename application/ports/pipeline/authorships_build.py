"""Port : SQL de construction de la table `authorships`.

Implémenté par `infrastructure.queries.pipeline.authorships_build.PgAuthorshipsBuildQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AuthorshipsBuildQueries(Protocol):
    """Opérations SQL pour promouvoir `source_authorships` → `authorships`."""

    def purge_authorships(self, conn: Connection) -> int: ...

    def insert_missing_authorships(self, conn: Connection) -> int: ...

    def prune_orphan_authorships(self, conn: Connection) -> int: ...

    def analyze_authorships(self, conn: Connection) -> None:
        """Met à jour les stats Postgres sur `authorships`.

        À appeler après une INSERT massive (typiquement `insert_missing_authorships` en mode rebuild_full) pour que le planner SQL de l'étape suivante (`propagate_authorship_attributes`) ait des estimations correctes. Sans ça, Postgres garde des stats périmées (`null_frac = 0` sur les colonnes fraîchement insérées) et choisit un Nested Loop O(n×m) au lieu d'un Hash Join, ce qui peut bloquer indéfiniment sur ~100k authorships.
        """
        ...

    def link_source_authorships_to_authorships(self, conn: Connection) -> int: ...

    def propagate_authorship_attributes(self, conn: Connection) -> int: ...

    def refresh_authorship_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `authorship_structures` (`REFRESH … CONCURRENTLY`)."""
        ...

    def count_authorships_in_perimeter(self, conn: Connection) -> int: ...

    def refresh_publications_in_perimeter(self, conn: Connection) -> int:
        """Matérialise `publications.in_perimeter` (rollup de `authorships.in_perimeter`).

        À appeler après `propagate_authorship_attributes` (qui pose
        `authorships.in_perimeter`). Idempotent.
        """
        ...
