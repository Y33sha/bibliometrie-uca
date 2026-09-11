"""Port : lecture des périmètres (ensembles de structures).

Implémenté par `infrastructure.pipeline.perimeter.PgPerimeterStructuresQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class EmptyExtractionPerimeterError(RuntimeError):
    """Le périmètre d'extraction ne contient aucune structure. Les phases qui en dépendent s'arrêtent en échec."""

    def __init__(self) -> None:
        super().__init__(
            "Le périmètre d'extraction est vide : la clé `perimeter_extraction` est absente de "
            "`config`, ou désigne un périmètre sans structure."
        )


class PerimeterStructuresQueries(Protocol):
    """Opérations sur les périmètres (lecture des structures, rematérialisation)."""

    def count_extraction_structures(self, conn: Connection) -> int:
        """Nombre de structures du périmètre d'extraction, zéro s'il n'est pas configuré."""
        ...

    def get_persons_structure_ids_list(self, conn: Connection) -> list[int]:
        """Structures du périmètre personnes, en liste — forme attendue d'un paramètre lié `ANY(:ids)`."""
        ...

    def refresh_perimeter_structures(self, conn: Connection) -> None:
        """Recompute la table matérialisée `perimeter_structures` (clôture des tutelles). Idempotent. Commit laissé au caller."""
        ...
