"""Lecture du périmètre : clôture de structures (matview `perimeter_structures`) et projection de la page admin.

Le périmètre associe des phases à des ensembles de structures, lu depuis `config` (`perimeter_extraction` : structures interrogées à l'extraction et reconnues dans les affiliations ; `perimeter_persons` : périmètre de création des personnes). La clôture récursive (`est_tutelle_de`) est matérialisée dans `perimeter_structures` par `refresh_perimeter_structures` (côté pipeline) ; ces fonctions ne font que la restituer.

Les fonctions libres sont partagées par l'extraction, le pipeline et les adapters : tout lecteur du périmètre passe par cette couche de lecture. `PgPerimetersQueries` implémente le port `application.ports.read_models.perimeters_queries`.
"""

from sqlalchemy import Connection, text

from application.ports.read_models.perimeters_queries import (
    PerimeterOut,
    PerimetersQueries,
    PerimeterStructureItem,
)

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


def _config_perimeter_code(conn: Connection, config_key: str, default: str) -> str:
    """Lit un code périmètre depuis la table config, ou rend `default` si la clé est absente."""
    row = conn.execute(
        text("SELECT value FROM config WHERE key = :key"),
        {"key": config_key},
    ).first()
    if row:
        val = row.value
        return val if isinstance(val, str) else default
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
        text("SELECT root_structure_ids FROM perimeters WHERE code = :code"),
        {"code": code},
    ).one_or_none()
    if not row:
        return []
    return list(row.root_structure_ids) if row.root_structure_ids else []


# ── Adapter Pg* pour le port read_models ──────────────────────────


class PgPerimetersQueries(PerimetersQueries):
    """Adapter SA pour `application.ports.read_models.perimeters_queries.PerimetersQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_perimeters_with_structures(self) -> list[PerimeterOut]:
        """Liste tous les périmètres avec leurs structures racines et le décompte de leur ensemble effectif, lu dans `perimeter_structures`."""
        perim_rows = self._conn.execute(
            text("SELECT id, code, name, root_structure_ids FROM perimeters ORDER BY id")
        ).all()
        perimeters: list[PerimeterOut] = []
        for p_row in perim_rows:
            root_ids = list(p_row.root_structure_ids or [])
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
                    root_structure_ids=root_ids,
                    structures=structures,
                    structure_count=len(resolved),
                )
            )
        return perimeters
