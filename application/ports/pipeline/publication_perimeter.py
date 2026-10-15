"""Port : recalcul, par le pipeline, de l'appartenance au périmètre des publications d'une personne, après son exclusion.

Implémenté par `pipeline.transformation.publications.reconciliation.publication_perimeter.PublicationPerimeterRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PublicationPerimeterRecompute(Protocol):
    """Recalcul ciblé de `publications.perimeter_evidence`."""

    def refresh_publications_of_person(self, conn: Connection, person_id: int) -> int:
        """Recalcule `publications.perimeter_evidence` pour les publications de la personne. Rend le nombre de publications changées."""
        ...
