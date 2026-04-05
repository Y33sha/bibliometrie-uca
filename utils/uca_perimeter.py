"""Calcul des périmètres de structures.

Lit les périmètres depuis les tables `perimeters` / `perimeter_rules`.
Fallback sur l'ancienne logique hardcodée si les tables n'existent pas.
"""


def get_perimeter_structure_ids(cur, perimeter_code: str) -> set[int]:
    """Retourne l'ensemble des structure_ids pour un périmètre donné.

    Chaque rule du périmètre définit une structure racine.
    Si include_children = TRUE, les enfants récursifs (via est_tutelle_de)
    sont inclus.
    """
    try:
        cur.execute("""
            SELECT pr.structure_id, pr.include_children
            FROM perimeter_rules pr
            JOIN perimeters p ON p.id = pr.perimeter_id
            WHERE p.code = %s
        """, (perimeter_code,))
        rules = cur.fetchall()
    except Exception:
        return _fallback_uca(cur) if perimeter_code == "uca" else set()

    if not rules:
        # Table existe mais périmètre non défini → fallback
        if perimeter_code == "uca":
            return _fallback_uca(cur)
        if perimeter_code == "uca_wide":
            return _fallback_uca_wide(cur)
        return set()

    result = set()
    for row in rules:
        struct_id = row[0] if isinstance(row, tuple) else row["structure_id"]
        include_children = row[1] if isinstance(row, tuple) else row["include_children"]
        result.add(struct_id)
        if include_children:
            cur.execute("""
                WITH RECURSIVE descendants AS (
                    SELECT child_id FROM structure_relations
                    WHERE parent_id = %s AND relation_type = 'est_tutelle_de'
                    UNION
                    SELECT sr.child_id FROM structure_relations sr
                    JOIN descendants d ON d.child_id = sr.parent_id
                    WHERE sr.relation_type = 'est_tutelle_de'
                )
                SELECT child_id FROM descendants
            """, (struct_id,))
            for r in cur.fetchall():
                result.add(r["child_id"] if isinstance(r, dict) else r[0])

    return result


def get_uca_structure_ids(cur) -> set[int]:
    """Retourne le périmètre UCA restreint (is_uca)."""
    return get_perimeter_structure_ids(cur, "uca")


def get_uca_structure_ids_wide(cur) -> set[int]:
    """Retourne le périmètre UCA élargi (structure_ids)."""
    return get_perimeter_structure_ids(cur, "uca_wide")


def get_uca_structure_ids_list(cur) -> list[int]:
    """Variante retournant une liste (pour usage dans les requêtes SQL ANY(%s))."""
    return list(get_uca_structure_ids(cur))


# Fallback si les tables perimeters n'existent pas encore
def _val(r, key):
    """Extrait une valeur d'un row (dict ou tuple)."""
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
