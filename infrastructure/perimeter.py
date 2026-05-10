"""Calcul des périmètres de structures.

Lit les périmètres depuis la table `perimeters` (colonne structure_ids).
Chaque structure racine inclut récursivement ses sous-structures
(via est_tutelle_de dans structure_relations).

L'association phase→périmètre est lue depuis la table `config` :
- perimeter_affiliations : périmètre pour la résolution des affiliations
- perimeter_persons : périmètre pour la création des personnes
"""

from typing import Any

from sqlalchemy import text


def get_perimeter_structure_ids(conn: Any, perimeter_code: str) -> set[int]:
    """Retourne l'ensemble des structure_ids pour un périmètre donné.

    Chaque structure listée dans perimeters.structure_ids est une racine.
    Ses descendants récursifs (via est_tutelle_de) sont inclus.
    """
    row = conn.execute(
        text("SELECT structure_ids FROM perimeters WHERE code = :code"),
        {"code": perimeter_code},
    ).first()
    root_ids = list(row.structure_ids) if row and row.structure_ids else None
    if not root_ids:
        return set()
    result = conn.execute(
        text("""
            WITH RECURSIVE descendants AS (
                SELECT unnest(CAST(:roots AS int[])) AS id
                UNION
                SELECT sr.child_id FROM structure_relations sr
                JOIN descendants d ON d.id = sr.parent_id
                WHERE sr.relation_type = 'est_tutelle_de'
            )
            SELECT id FROM descendants
        """),
        {"roots": root_ids},
    )
    return {row.id for row in result}


# ── Fonctions par rôle (lisent la config) ──


def _config_perimeter_code(conn: Any, config_key: str, default: str) -> str:
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


def get_affiliations_structure_ids(conn: Any) -> set[int]:
    """Périmètre pour la résolution des affiliations (structure_ids)."""
    code = _config_perimeter_code(conn, "perimeter_affiliations", "uca_wide")
    return get_perimeter_structure_ids(conn, code)


def get_persons_structure_ids(conn: Any) -> set[int]:
    """Périmètre pour la création des personnes (in_perimeter)."""
    code = _config_perimeter_code(conn, "perimeter_persons", "uca")
    return get_perimeter_structure_ids(conn, code)


def get_persons_structure_ids_list(conn: Any) -> list[int]:
    """Variante liste (pour usage dans les requêtes SQL ANY(:ids))."""
    return list(get_persons_structure_ids(conn))


def get_persons_perimeter_root_ids(conn: Any) -> list[int]:
    """Racines du périmètre "persons" (sans expansion par `est_tutelle_de`).

    À distinguer de `get_persons_structure_ids(...)` qui retourne la
    clôture transitive : les racines + tous les labos descendants. Utilisé
    quand un code appelant veut filtrer explicitement les racines du périmètre
    (ex. exclure l'UCA des tutelles affichées pour un labo).
    """
    code = _config_perimeter_code(conn, "perimeter_persons", "uca")
    row = conn.execute(
        text("SELECT structure_ids FROM perimeters WHERE code = :code"),
        {"code": code},
    ).one_or_none()
    if not row:
        return []
    return list(row.structure_ids) if row.structure_ids else []
