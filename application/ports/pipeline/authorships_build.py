"""Port : construction de la table `authorships` depuis les `source_authorships`, phase `authorships`.

Implémenté par `infrastructure.queries.pipeline.authorships_build.PgAuthorshipsBuildQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AuthorshipsBuildQueries(Protocol):
    """Promotion des `source_authorships` en `authorships` consolidées."""

    def purge_authorships(self, conn: Connection) -> int:
        """Vide `authorships` et délie les `source_authorships` qui y pointaient. Retourne le nombre de lignes purgées.

        Réservé au mode `full`, qui repart de zéro ; le build incrémental s'en passe, sa logique étant idempotente.
        """
        ...

    def insert_missing_authorships(self, conn: Connection) -> int:
        """Crée les `authorships` manquantes : les paires `(publication_id, person_id)` qu'atteste une `source_authorship` rattachée à une publication active. Retourne le rowcount.

        Une paire inscrite dans `rejected_authorships` est écartée par un anti-join : le rejet admin survit aux runs suivants.
        """
        ...

    def prune_orphan_authorships(self, conn: Connection) -> int:
        """Supprime les `authorships` qu'aucune `source_authorship` n'atteste — auteur retiré de toutes les sources. Retourne le nombre supprimé.

        Inverse d'`insert_missing_authorships`, à tourner à chaque build : l'incrémental étant add-only, une orpheline y survivrait jusqu'au prochain `full`.
        """
        ...

    def analyze_authorships(self, conn: Connection) -> None:
        """Met à jour les stats Postgres sur `authorships`.

        À appeler après l'insertion (`insert_missing_authorships`) pour que le planner SQL des étapes suivantes (`link_source_authorships_to_authorships`, `propagate_authorship_attributes`) ait des estimations correctes sur les lignes fraîchement insérées. Sans ça, Postgres garde des stats périmées (`null_frac = 0`) et choisit un Nested Loop O(n×m) au lieu d'un Hash Join, ce qui peut bloquer indéfiniment.
        """
        ...

    def link_source_authorships_to_authorships(self, conn: Connection) -> int:
        """Pose `source_authorships.authorship_id` sur les signatures encore non liées, toutes sources confondues. Retourne le nombre de lignes reliées."""
        ...

    def analyze_source_authorships(self, conn: Connection) -> None:
        """Met à jour les stats Postgres sur `source_authorships`.

        À appeler après `link_source_authorships_to_authorships`, qui vient de poser `authorship_id` sur des centaines de milliers de lignes : en état committé la colonne est quasi 100% NULL (`null_frac ≈ 1`), donc sans ce ANALYZE le planner de `propagate_authorship_attributes` estime que `WHERE authorship_id IS NOT NULL` ne ramène rien (`rows = 1`) et part en Nested Loop. L'ANALYZE intra-transaction voit les mises à jour non committées de la transaction courante.
        """
        ...

    def propagate_authorship_attributes(self, conn: Connection) -> int:
        """Recompose les attributs dérivés de chaque authorship depuis ses `source_authorships` liées. Retourne le nombre d'authorships modifiées.

        - `author_position` : valeur de la source la plus prioritaire qui la renseigne (`SOURCE_PRIORITY`) — seul attribut qui départage les sources.
        - `is_corresponding` et `in_perimeter` : `bool_or`. Aucune source n'émet de FALSE explicite ; son silence ne saurait écraser l'affirmation d'une autre.
        - `roles` : union triée.

        Convergente : une valeur que plus aucune source n'atteste retombe — TRUE périmé à FALSE, rôle disparu retiré.
        """
        ...

    def refresh_authorship_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `authorship_structures` (`REFRESH … CONCURRENTLY`)."""
        ...

    def refresh_publication_structures(self, conn: Connection) -> None:
        """Rafraîchit la matview `publication_structures` (publi↔structure), après `refresh_authorship_structures` dont elle dérive."""
        ...

    def count_authorships_in_perimeter(self, conn: Connection) -> int:
        """Nombre d'`authorships` dont `in_perimeter` est vrai."""
        ...

    def refresh_publications_in_perimeter(self, conn: Connection) -> int:
        """Matérialise `publications.in_perimeter` (rollup de `authorships.in_perimeter`).

        À appeler après `propagate_authorship_attributes`, qui pose `authorships.in_perimeter`. Idempotent.
        """
        ...
