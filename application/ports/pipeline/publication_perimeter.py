"""Port : recalcul, par le pipeline, de l'appartenance au périmètre des publications, après une décision de l'administration sur une personne ou sur ses contributions.

Implémenté par `pipeline.transformation.publications.publication_perimeter.PublicationPerimeterRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PublicationPerimeterRecompute(Protocol):
    """Recalcul ciblé de `publications.perimeter_evidence`."""

    def refresh_publications_of_person(self, conn: Connection, person_id: int) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications de la personne. Rend le nombre de publications changées."""
        ...

    def refresh_publications(self, conn: Connection, publication_ids: list[int]) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications `publication_ids`. Rend le nombre de publications changées."""
        ...
