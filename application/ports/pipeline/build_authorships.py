"""Port : rattachement de signatures orphelines à une personne.

Implémenté par `pipeline.transformation.publications.authorships.authorships_queries.AuthorshipsBuild`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AuthorshipsBuildQueries(Protocol):
    """Rattachement de signatures orphelines à une personne."""

    def assign_orphan_source_authorships_to_person(
        self, conn: Connection, person_id: int, source_authorship_ids: list[int]
    ) -> list[int]:
        """Pose `person_id` sur les signatures orphelines du lot et retourne leurs ids ; les signatures déjà liées restent intactes."""
        ...
