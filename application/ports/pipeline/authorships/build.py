"""Port : construction de la table `authorships` depuis les `source_authorships`, phase `authorships`.

Implémenté par `pipeline.transformation.publications.authorships.authorships_queries.AuthorshipsBuild`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AuthorshipsBuildQueries(Protocol):
    """Promotion des `source_authorships` en `authorships` consolidées (phase `authorships`), et variantes par lot de cette construction pour l'attribution admin d'orphelines à une personne."""

    def purge_authorships(self, conn: Connection) -> int:
        """Vide `authorships`. Retourne le nombre de lignes purgées.

        Réservé au mode `full`, qui repart de zéro ; le build incrémental s'en passe, sa logique étant idempotente.
        """
        ...

    def insert_missing_authorships(self, conn: Connection) -> int:
        """Crée les `authorships` manquantes : les paires `(publication_id, person_id)` qu'atteste une `source_authorship` rattachée à une publication active. Retourne le rowcount.

        Une paire rejetée est écartée : une publication est rejetée pour une personne dès qu'une de ses notices l'est. Une signature confirmée à la personne l'emporte sur le rejet : la confirmation vise la signature elle-même.
        """
        ...

    def prune_orphan_authorships(self, conn: Connection) -> int:
        """Supprime les `authorships` qu'aucune `source_authorship` n'atteste — auteur retiré de toutes les sources. Retourne le nombre supprimé.

        Inverse d'`insert_missing_authorships`, à tourner à chaque build : l'incrémental étant add-only, une orpheline y survivrait jusqu'au prochain `full`.
        """
        ...

    def propagate_authorship_attributes(self, conn: Connection) -> int:
        """Recompose les attributs dérivés de chaque authorship depuis les `source_authorships` qui l'attestent : même publication par leur notice, même personne. Retourne le nombre d'authorships modifiées.

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

    # ── Variantes par lot pour l'attribution admin d'orphelines ────

    def assign_orphan_source_authorships_to_person(
        self, conn: Connection, person_id: int, source_authorship_ids: list[int]
    ) -> list[int]:
        """Pose `person_id` sur les signatures orphelines du lot et retourne leurs ids ; les signatures déjà liées restent intactes."""
        ...

    def create_authorships_from_sources(
        self,
        conn: Connection,
        person_id: int,
        source_authorship_ids: list[int],
        source_priority: tuple[str, ...],
    ) -> None:
        """Crée les lignes consolidées manquantes pour la personne, une par publication couverte par le lot, depuis la signature la plus prioritaire (`source_priority`) — variante par lot de la construction. Écarte les paires figurant dans `rejected_authorships`."""
        ...
