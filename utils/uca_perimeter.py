"""Calcul des périmètres de structures.

Lit les périmètres depuis la table `perimeters` (colonne structure_ids).
Chaque structure racine inclut récursivement ses sous-structures
(via est_tutelle_de dans structure_relations).
"""


def get_perimeter_structure_ids(cur, perimeter_code: str) -> set[int]:
    """Retourne l'ensemble des structure_ids pour un périmètre donné.

    Chaque structure listée dans perimeters.structure_ids est une racine.
    Ses descendants récursifs (via est_tutelle_de) sont inclus.
    """
    try:
        cur.execute(
            "SELECT structure_ids FROM perimeters WHERE code = %s",
            (perimeter_code,))
        row = cur.fetchone()
    except Exception:
        return _fallback_uca(cur) if perimeter_code == "uca" else set()

    if not row:
        if perimeter_code == "uca":
            return _fallback_uca(cur)
        if perimeter_code == "uca_wide":
            return _fallback_uca_wide(cur)
        return set()

    root_ids = row["structure_ids"] if isinstance(row, dict) else row[0]
    if not root_ids:
        return set()

    # Résoudre les descendants récursifs en une seule requête
    cur.execute("""
        WITH RECURSIVE descendants AS (
            SELECT unnest(%s::int[]) AS id
            UNION
            SELECT sr.child_id FROM structure_relations sr
            JOIN descendants d ON d.id = sr.parent_id
            WHERE sr.relation_type = 'est_tutelle_de'
        )
        SELECT id FROM descendants
    """, (root_ids,))

    return {r["id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()}


def get_uca_structure_ids(cur) -> set[int]:
    """Retourne le périmètre UCA restreint (is_uca)."""
    return get_perimeter_structure_ids(cur, "uca")


def get_uca_structure_ids_wide(cur) -> set[int]:
    """Retourne le périmètre UCA élargi (structure_ids)."""
    return get_perimeter_structure_ids(cur, "uca_wide")


def get_uca_structure_ids_list(cur) -> list[int]:
    """Variante retournant une liste (pour usage dans les requêtes SQL ANY(%s))."""
    return list(get_uca_structure_ids(cur))


# Fallback si la table perimeters n'existe pas encore
def _val(r, key):
    return r[key] if isinstance(r, dict) else r[0]


def _fallback_uca(cur) -> set[int]:
    cur.execute("""
        SELECT s.id FROM structures s WHERE s.code = 'uca'
        UNION
        SELECT sr.child_id FROM structure_relations sr
        JOIN structures s ON s.id = sr.parent_id
        WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
    """)
    return {_val(r, "id") for r in cur.fetchall()}


def _fallback_uca_wide(cur) -> set[int]:
    restricted = _fallback_uca(cur)
    cur.execute("""
        SELECT sr.parent_id FROM structure_relations sr
        JOIN structures s ON s.id = sr.child_id
        WHERE s.code = 'uca' AND sr.relation_type = 'est_partenaire_de'
    """)
    return restricted | {_val(r, "parent_id") for r in cur.fetchall()}
