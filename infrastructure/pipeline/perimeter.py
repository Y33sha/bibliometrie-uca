"""Recompute du matview de périmètre + adapter de la phase persons.

`refresh_perimeter_structures` matérialise dans `perimeter_structures` la clôture récursive (`est_tutelle_de`) des racines `perimeters.root_structure_ids`. `PgPerimeterStructuresQueries` fournit à la phase persons la clôture du périmètre (lue via `read_models`) et son recompute.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.perimeter_structures import PerimeterStructuresQueries
from domain.structures.relations import StructureRelationType
from infrastructure.read_models.perimeters import get_persons_structure_ids_list


def refresh_perimeter_structures(conn: Connection) -> None:
    """Recompute la table matérialisée `perimeter_structures` : pour chaque périmètre, la clôture récursive (`est_tutelle_de`) de ses racines `perimeters.root_structure_ids`, filtrée aux structures existantes. Idempotent (DELETE + réinsertion complète). Commit laissé au caller.

    Seule implémentation de la clôture d'un périmètre — `get_perimeter_structure_ids` lit cette table. À rejouer à chaque édition de `perimeters.root_structure_ids` ou `structure_relations`.
    """
    conn.execute(text("DELETE FROM perimeter_structures"))
    conn.execute(
        text(f"""
            INSERT INTO perimeter_structures (perimeter_id, structure_id)
            WITH RECURSIVE descendants AS (
                SELECT p.id AS perimeter_id, s.structure_id
                FROM perimeters p
                CROSS JOIN LATERAL unnest(p.root_structure_ids) AS s(structure_id)
                UNION
                SELECT d.perimeter_id, sr.child_id
                FROM descendants d
                JOIN structure_relations sr ON sr.parent_id = d.structure_id
                WHERE sr.relation_type = '{StructureRelationType.EST_TUTELLE_DE.value}'
            )
            SELECT DISTINCT d.perimeter_id, d.structure_id
            FROM descendants d
            WHERE EXISTS (SELECT 1 FROM structures st WHERE st.id = d.structure_id)
        """)
    )


class PgPerimeterStructuresQueries(PerimeterStructuresQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.perimeter_structures.PerimeterStructuresQueries`."""

    def get_persons_structure_ids_list(self, conn: Connection) -> list[int]:
        return get_persons_structure_ids_list(conn)

    def refresh_perimeter_structures(self, conn: Connection) -> None:
        refresh_perimeter_structures(conn)
