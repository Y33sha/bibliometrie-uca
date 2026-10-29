"""Lecture des périmètres : structures de chaque périmètre (table `perimeter_structures`) et projection de la page d'administration.

`config` désigne deux périmètres : `perimeter_extraction`, structures interrogées au moissonnage et reconnues dans les affiliations ; `perimeter_persons`, périmètre de création des personnes, à défaut celui d'extraction. Une clé absente vaut périmètre vide. `refresh_perimeter_structures` (pipeline) calcule les structures de chaque périmètre ; ce module les lit.

Le moissonnage, le pipeline et les adaptateurs lisent tous le périmètre par ces fonctions.
"""

from sqlalchemy import Connection, text

from domain.config import (
    BRAND_HUE_KEY,
    DEFAULT_BRAND_HUE,
    PERIMETER_EXTRACTION_KEY,
    PERIMETER_PERSONS_KEY,
    SITE_TITLE_KEY,
)
from infrastructure.read_models.perimeters.models import (
    InstitutionOut,
    PerimeterOut,
    PerimeterStructureItem,
)

# ── Fonctions libres ──────────────────────────────────────────────


def get_perimeter_structure_ids(conn: Connection, perimeter_code: str) -> set[int]:
    """Structures d'un périmètre, racines et descendantes, lues dans `perimeter_structures`."""
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


def _config_perimeter_code(conn: Connection, config_key: str) -> str | None:
    """Code de périmètre lu dans `config`, ou `None` si la clé est absente ou vide."""
    value = conn.execute(
        text("SELECT value FROM config WHERE key = :key"),
        {"key": config_key},
    ).scalar_one_or_none()
    return value if isinstance(value, str) and value else None


def extraction_perimeter_code(conn: Connection) -> str | None:
    """Code du périmètre d'extraction, ou `None` s'il n'est pas configuré."""
    return _config_perimeter_code(conn, PERIMETER_EXTRACTION_KEY)


def persons_perimeter_code(conn: Connection) -> str | None:
    """Code du périmètre des personnes, à défaut celui du périmètre d'extraction."""
    return _config_perimeter_code(conn, PERIMETER_PERSONS_KEY) or extraction_perimeter_code(conn)


def get_extraction_structure_ids(conn: Connection) -> set[int]:
    """Structures du périmètre d'extraction, vide s'il n'est pas configuré."""
    code = extraction_perimeter_code(conn)
    return get_perimeter_structure_ids(conn, code) if code else set()


def get_hal_collections(conn: Connection) -> dict[str, str]:
    """Collections HAL des structures du périmètre d'extraction qui en ont une : libellé par code."""
    structure_ids = get_extraction_structure_ids(conn)
    if not structure_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT hal_collection, COALESCE(acronym, name) AS label "
            "FROM structures "
            "WHERE id = ANY(:ids) "
            "AND hal_collection IS NOT NULL AND hal_collection != ''"
        ),
        {"ids": list(structure_ids)},
    ).all()
    return {r.hal_collection: r.label for r in rows}


def get_extraction_api_ids(conn: Connection, source: str) -> list[str]:
    """Identifiants d'API d'une source pour les structures du périmètre d'extraction (`structures.api_ids[source]`), sans doublon, dans l'ordre."""
    struct_ids = get_extraction_structure_ids(conn)
    if not struct_ids:
        return []
    rows = conn.execute(
        text("SELECT api_ids->:src AS ids FROM structures WHERE id = ANY(:ids) AND api_ids ? :src"),
        {"src": source, "ids": list(struct_ids)},
    ).all()
    result: list[str] = []
    for row in rows:
        ids = row.ids
        if isinstance(ids, list):
            result.extend(ids)
        elif isinstance(ids, str):
            # Tolérance d'un scalaire (cf. `StructureApiIds._ensure_list`).
            result.append(ids)
    return list(dict.fromkeys(result))


def get_persons_structure_ids(conn: Connection) -> set[int]:
    """Structures du périmètre des personnes, vide s'il n'est pas configuré."""
    code = persons_perimeter_code(conn)
    return get_perimeter_structure_ids(conn, code) if code else set()


def get_persons_structure_ids_list(conn: Connection) -> list[int]:
    """Mêmes structures que `get_persons_structure_ids`, en liste : `ANY(:ids)` refuse un `set`."""
    return list(get_persons_structure_ids(conn))


def get_persons_perimeter_root_ids(conn: Connection) -> list[int]:
    """Racines du périmètre des personnes, sans leurs sous-structures (que renvoie `get_persons_structure_ids`). Sert à filtrer les racines, par exemple pour retirer l'établissement des tutelles affichées pour un laboratoire."""
    code = persons_perimeter_code(conn)
    if not code:
        return []
    row = conn.execute(
        text("SELECT root_structure_ids FROM perimeters WHERE code = :code"),
        {"code": code},
    ).one_or_none()
    if not row:
        return []
    return list(row.root_structure_ids) if row.root_structure_ids else []


def get_persons_perimeter_name(conn: Connection) -> str:
    """Nom du périmètre des personnes, qui désigne l'établissement dans l'interface, ou son code s'il manque. Vide sans périmètre configuré."""
    code = persons_perimeter_code(conn)
    if not code:
        return ""
    name = conn.execute(
        text("SELECT name FROM perimeters WHERE code = :code"), {"code": code}
    ).scalar_one_or_none()
    return name or code


# ── Lectures pour l'API ───────────────────────────────────────────


class PerimetersQueries:
    """Lectures sur les périmètres et l'établissement servi par l'instance."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def institution(self) -> InstitutionOut:
        values = dict(
            self._conn.execute(
                text("SELECT key, value FROM config WHERE key IN (:title, :hue)"),
                {"title": SITE_TITLE_KEY, "hue": BRAND_HUE_KEY},
            ).all()
        )
        hue = values.get(BRAND_HUE_KEY)
        return InstitutionOut(
            name=get_persons_perimeter_name(self._conn),
            root_structure_ids=get_persons_perimeter_root_ids(self._conn),
            title=values.get(SITE_TITLE_KEY) or None,
            brand_hue=hue if isinstance(hue, int) else DEFAULT_BRAND_HUE,
        )

    def list_perimeters_with_structures(self) -> list[PerimeterOut]:
        """Tous les périmètres, avec leurs structures racines et leur nombre de structures, lu dans `perimeter_structures`."""
        perim_rows = self._conn.execute(
            text("SELECT id, code, name, root_structure_ids FROM perimeters ORDER BY id")
        ).all()
        persons_code = persons_perimeter_code(self._conn)
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
                    is_persons=p_row.code == persons_code,
                )
            )
        return perimeters
