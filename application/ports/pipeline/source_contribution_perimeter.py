"""Port : recalcul ciblé du périmètre de contributions sources, après une correction d'adresse par l'administration.

Implémenté par `pipeline.transformation.structures.perimeter_evidence.SourceContributionPerimeterRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class SourceContributionPerimeterRecompute(Protocol):
    """Recalcul ciblé du périmètre après une correction d'adresse."""

    def recompute_perimeter(
        self,
        conn: Connection,
        source_contribution_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Recalcule les indices de l'entrée dans le périmètre des contributions sources données, de leurs groupes et de leurs publications, par les mêmes requêtes que le pipeline. Un enregistrement source sans publication dont une contribution source entre dans le périmètre est marqué pour la réconciliation."""
        ...
