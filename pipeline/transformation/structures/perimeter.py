"""Périmètres : clôture des tutelles matérialisée dans `perimeter_structures`, lecture des structures d'un périmètre, condition d'exécution des phases qui dépendent du périmètre d'extraction.

`refresh_perimeter_structures` est rejouée en tête de pipeline, avant toute phase, et par l'administration après l'édition d'un périmètre, d'une structure ou d'une tutelle (`PerimeterStructures`)."""

from sqlalchemy import Connection, text

from infrastructure.read_models.perimeters import get_persons_structure_ids_list


class EmptyExtractionPerimeterError(RuntimeError):
    """Le périmètre d'extraction ne contient aucune structure. Les phases qui en dépendent s'arrêtent en échec."""

    def __init__(self) -> None:
        super().__init__(
            "Le périmètre d'extraction est vide : la clé `perimeter_extraction` est absente de "
            "`config`, ou désigne un périmètre sans structure."
        )


def refresh_perimeter_structures(conn: Connection) -> None:
    """Recompute la table matérialisée `perimeter_structures` : pour chaque périmètre, la clôture récursive (`est_tutelle_de`) de ses racines `perimeters.root_structure_ids`, filtrée aux structures existantes. Idempotent (DELETE + réinsertion complète). Commit laissé au caller.

    Seule implémentation de la clôture d'un périmètre — `get_perimeter_structure_ids` lit cette table. À rejouer à chaque édition de `perimeters.root_structure_ids` ou `structure_parents`.
    """
    conn.execute(text("DELETE FROM perimeter_structures"))
    conn.execute(
        text("""
            INSERT INTO perimeter_structures (perimeter_id, structure_id)
            WITH RECURSIVE descendants AS (
                SELECT p.id AS perimeter_id, s.structure_id
                FROM perimeters p
                CROSS JOIN LATERAL unnest(p.root_structure_ids) AS s(structure_id)
                UNION
                SELECT d.perimeter_id, sr.child_id
                FROM descendants d
                JOIN structure_parents sr ON sr.parent_id = d.structure_id
            )
            SELECT DISTINCT d.perimeter_id, d.structure_id
            FROM descendants d
            WHERE EXISTS (SELECT 1 FROM structures st WHERE st.id = d.structure_id)
        """)
    )


class PerimeterStructures:
    """Clôture des tutelles des périmètres : rematérialisation et lecture (port injecté par l'API)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def refresh(self) -> None:
        refresh_perimeter_structures(self._conn)

    def persons_structure_ids(self) -> list[int]:
        return get_persons_structure_ids_list(self._conn)
