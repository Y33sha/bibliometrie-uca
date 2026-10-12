"""Port : construction des `authorships` d'une personne, à l'attribution de signatures orphelines.

Implémenté par `pipeline.transformation.publications.authorships.authorships_queries.AuthorshipsBuild`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AuthorshipsBuildQueries(Protocol):
    """Rattachement de signatures orphelines à une personne, et construction des `authorships` correspondantes."""

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
