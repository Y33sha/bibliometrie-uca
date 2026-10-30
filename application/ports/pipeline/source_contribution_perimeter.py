"""Port : recalcul ciblé du périmètre de contributions sources, après une correction d'adresse par l'administration.

Implémenté par `pipeline.transformation.structures.perimeter_evidence.SourceContributionPerimeterRecompute`.
"""

from typing import Protocol


class SourceContributionPerimeterRecompute(Protocol):
    """Recalcul ciblé du périmètre après une correction d'adresse."""

    def recompute_perimeter(
        self,
        source_contribution_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Recalcule les indices d'appartenance au périmètre des contributions sources données, de leurs contributions et de leurs publications, par les mêmes requêtes que le pipeline.

        Un enregistrement source sans publication est marqué pour la réconciliation si une de ses contributions sources entre dans le périmètre.
        """
        ...
