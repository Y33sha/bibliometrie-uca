"""Port : recalcul ciblé du périmètre de signatures, après une correction d'adresse par l'administration.

Implémenté par `pipeline.transformation.structures.in_perimeter.InPerimeterRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class AffiliationsQueries(Protocol):
    """Recalcul ciblé du périmètre après une correction d'adresse."""

    def recompute_perimeter(
        self,
        conn: Connection,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Recalcule les indices de l'entrée dans le périmètre des signatures données, de leurs authorships et de leurs publications, par les mêmes requêtes que le pipeline. Un enregistrement sans publication dont une signature entre dans le périmètre est marqué `keys_dirty`."""
        ...
