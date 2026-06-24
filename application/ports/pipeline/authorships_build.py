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

        À appeler après l'insertion (`insert_missing_authorships`) pour que le planner SQL des étapes suivantes (`link_source_authorships_to_authorships`, `propagate_authorship_attributes`) ait des estimations correctes sur les lignes fraîchement insérées. Sans ça, Postgres garde des stats périmées (`null_frac = 0`) et choisit un Nested Loop O(n×m) au lieu d'un Hash Join, ce qui peut bloquer indéfiniment.
        """
        ...

    def link_source_authorships_to_authorships(self, conn: Connection) -> int: ...

    def analyze_source_authorships(self, conn: Connection) -> None:
        """Met à jour les stats Postgres sur `source_authorships`.

        À appeler après `link_source_authorships_to_authorships`, qui vient de poser `authorship_id` sur des centaines de milliers de lignes : en état committé la colonne est quasi 100% NULL (`null_frac ≈ 1`), donc sans ce ANALYZE le planner de `propagate_authorship_attributes` estime que `WHERE authorship_id IS NOT NULL` ne ramène rien (`rows = 1`) et part en Nested Loop. L'ANALYZE intra-transaction voit les mises à jour non committées de la transaction courante.
        """
        ...

    def propagate_authorship_attributes(self, conn: Connection) -> int: ...

    def refresh_authorship_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `authorship_structures` (`REFRESH … CONCURRENTLY`)."""
        ...

    def refresh_publication_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `publication_structures` (publi↔structure, après
        `refresh_authorship_structures` dont elle dérive)."""
        ...

    def count_authorships_in_perimeter(self, conn: Connection) -> int: ...

    def refresh_publications_in_perimeter(self, conn: Connection) -> int:
        """Matérialise `publications.in_perimeter` (rollup de `authorships.in_perimeter`).

        À appeler après `propagate_authorship_attributes` (qui pose
        `authorships.in_perimeter`). Idempotent.
        """
        ...
