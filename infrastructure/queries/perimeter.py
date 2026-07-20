"""Calcul des périmètres de structures + adapter SQL pour les ports.

Lit les périmètres depuis la table `perimeters` (colonne `structure_ids`). Chaque structure racine inclut récursivement ses sous-structures (via `est_tutelle_de` dans `structure_relations`).

L'association phase → périmètre est lue depuis la table `config` :
- `perimeter_extraction` : structures interrogées à l'extraction et reconnues dans les affiliations
- `perimeter_persons` : périmètre pour la création des personnes

Expose :
- Fonctions libres (`get_perimeter_structure_ids`, `get_persons_structure_ids`, …) consommées directement par les CLIs pipeline.
- `PgPerimeterQueries` / `PgPerimetersQueries` : adapters pour les ports `application.ports.pipeline.perimeter` et `application.ports.api.perimeters_queries`.
"""

from sqlalchemy import Connection, text

from application.ports.api.perimeters_queries import (
    PerimeterOut,
    PerimetersQueries,
    PerimeterStructureItem,
)
from application.ports.pipeline.perimeter import PerimeterQueries

# ── Fonctions libres ──────────────────────────────────────────────


def get_perimeter_structure_ids(conn: Connection, perimeter_code: str) -> set[int]:
    """Ensemble des `structure_id` du périmètre `perimeter_code` — racines et descendants (`est_tutelle_de`) — lu depuis la table matérialisée `perimeter_structures`.

    La clôture est calculée par `refresh_perimeter_structures` (en tête de pipeline, à chaque édition admin, et au début d'`affiliations`) ; cette lecture ne fait que la restituer.
    """
    result = conn.execute(
        text("""
            SELECT ps.structure_id
            FROM perimeter_structures ps
            JOIN perimeters p ON p.id = ps.perimeter_id
            WHERE p.code = :code
        """),
        {"code": perimeter_code},
    )
    return {row.structure_id for row in result}


def refresh_perimeter_structures(conn: Connection) -> None:
    """Recompute la table matérialisée `perimeter_structures` : pour chaque périmètre, la clôture récursive (`est_tutelle_de`) de ses racines `perimeters.structure_ids`, filtrée aux structures existantes. Idempotent (DELETE + réinsertion complète). Commit laissé au caller.

    Seule implémentation de la clôture d'un périmètre — `get_perimeter_structure_ids` lit cette table. À rejouer à chaque édition de `perimeters.structure_ids` ou `structure_relations`.
    """
    conn.execute(text("DELETE FROM perimeter_structures"))
    conn.execute(
        text("""
            INSERT INTO perimeter_structures (perimeter_id, structure_id)
            WITH RECURSIVE descendants AS (
                SELECT p.id AS perimeter_id, s.structure_id
                FROM perimeters p
                CROSS JOIN LATERAL unnest(p.structure_ids) AS s(structure_id)
                UNION
                SELECT d.perimeter_id, sr.child_id
                FROM descendants d
                JOIN structure_relations sr ON sr.parent_id = d.structure_id
                WHERE sr.relation_type = 'est_tutelle_de'
            )
            SELECT DISTINCT d.perimeter_id, d.structure_id
            FROM descendants d
            WHERE EXISTS (SELECT 1 FROM structures st WHERE st.id = d.structure_id)
        """)
    )


def _config_perimeter_code(conn: Connection, config_key: str, default: str) -> str:
    """Lit un code périmètre depuis la table config."""
    try:
        row = conn.execute(
            text("SELECT value FROM config WHERE key = :key"),
            {"key": config_key},
        ).first()
        if row:
            val = row.value
            return val if isinstance(val, str) else default
    except Exception:
        pass
    return default


def get_persons_structure_ids(conn: Connection) -> set[int]:
    """Périmètre pour la création des personnes (`in_perimeter`)."""
    code = _config_perimeter_code(conn, "perimeter_persons", "uca")
    return get_perimeter_structure_ids(conn, code)


def get_persons_structure_ids_list(conn: Connection) -> list[int]:
    """Variante liste de `get_persons_structure_ids` (un `set` n'est pas un paramètre lié valide pour `ANY(:ids)`)."""
    return list(get_persons_structure_ids(conn))


def get_persons_perimeter_root_ids(conn: Connection) -> list[int]:
    """Racines du périmètre "persons" (sans expansion par `est_tutelle_de`).

    À distinguer de `get_persons_structure_ids(...)` qui retourne la clôture transitive (racines + tous les labos descendants). Utilisé quand un code appelant veut filtrer explicitement les racines du périmètre (ex. exclure l'UCA des tutelles affichées pour un labo).
    """
    code = _config_perimeter_code(conn, "perimeter_persons", "uca")
    row = conn.execute(
        text("SELECT structure_ids FROM perimeters WHERE code = :code"),
        {"code": code},
    ).one_or_none()
    if not row:
        return []
    return list(row.structure_ids) if row.structure_ids else []


# ── Adapters Pg* pour les ports ───────────────────────────────────


class PgPerimeterQueries(PerimeterQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.perimeter.PerimeterQueries`."""

    def get_persons_structure_ids_list(self, conn: Connection) -> list[int]:
        return get_persons_structure_ids_list(conn)

    def refresh_perimeter_structures(self, conn: Connection) -> None:
        refresh_perimeter_structures(conn)


class PgPerimetersQueries(PerimetersQueries):
    """Adapter SA pour `application.ports.api.perimeters_queries.PerimetersQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_perimeters_with_structures(self) -> list[PerimeterOut]:
        """Liste tous les périmètres avec leurs structures racines et le décompte de leur ensemble effectif, lu dans `perimeter_structures`."""
        perim_rows = self._conn.execute(
            text("SELECT id, code, name, structure_ids FROM perimeters ORDER BY id")
        ).all()
        perimeters: list[PerimeterOut] = []
        for p_row in perim_rows:
            root_ids = list(p_row.structure_ids or [])
            if root_ids:
                struct_rows = self._conn.execute(
                    text(
                        "SELECT id, name, acronym, code FROM structures "
                        "WHERE id = ANY(:ids) ORDER BY name"
                    ),
                    {"ids": root_ids},
                ).all()
                structures = [
                    PerimeterStructureItem(id=r.id, name=r.name, acronym=r.acronym, code=r.code)
                    for r in struct_rows
                ]
            else:
                structures = []
            resolved = get_perimeter_structure_ids(self._conn, p_row.code)
            perimeters.append(
                PerimeterOut(
                    id=p_row.id,
                    code=p_row.code,
                    name=p_row.name,
                    structure_ids=root_ids,
                    structures=structures,
                    structure_count=len(resolved),
                )
            )
        return perimeters
