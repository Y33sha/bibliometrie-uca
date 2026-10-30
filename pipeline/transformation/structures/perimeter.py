"""Périmètres : structures de chaque périmètre, matérialisées dans `perimeter_structures`, et erreur du périmètre d'extraction vide.

La table se recalcule avant toute phase du pipeline, et après chaque édition d'un périmètre, d'une structure ou d'une tutelle par l'administration (`PerimeterStructures`)."""

from sqlalchemy import Connection, text

from infrastructure.read_models.perimeters.queries import get_persons_structure_ids_list


class EmptyExtractionPerimeterError(RuntimeError):
    """Erreur du périmètre d'extraction sans structure. Les phases dépendantes de ce périmètre s'arrêtent en échec."""

    def __init__(self) -> None:
        super().__init__(
            "Le périmètre d'extraction est vide : la clé `perimeter_extraction` est absente de "
            "`config`, ou désigne un périmètre sans structure."
        )


def refresh_perimeter_structures(conn: Connection) -> None:
    """Recalcule `perimeter_structures` : pour chaque périmètre, ses structures racines et les structures sous leur tutelle, directement ou non. Seules comptent les structures existantes. L'appelant commite."""
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
    """Structures des périmètres, pour l'API : recalcul et lecture."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def refresh(self) -> None:
        refresh_perimeter_structures(self._conn)

    def persons_structure_ids(self) -> list[int]:
        return get_persons_structure_ids_list(self._conn)
