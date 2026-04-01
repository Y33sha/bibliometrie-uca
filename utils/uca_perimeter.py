"""Définition unique du périmètre UCA (structures).

Le périmètre restreint (is_uca) inclut :
- UCA elle-même
- Les structures dont UCA est tutelle (est_tutelle_de)

N'inclut PAS les partenaires (CHU, INP…) ni les tutelles nationales.
"""


def get_uca_structure_ids(cur) -> set[int]:
    """Retourne l'ensemble des structure_ids dans le périmètre UCA restreint."""
    cur.execute("""
        SELECT s.id FROM structures s WHERE s.code = 'uca'
        UNION
        SELECT sr.child_id FROM structure_relations sr
        JOIN structures s ON s.id = sr.parent_id
        WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
    """)
    return {r["id"] for r in cur.fetchall()}


def get_uca_structure_ids_list(cur) -> list[int]:
    """Variante retournant une liste (pour usage dans les requêtes SQL ANY(%s))."""
    return list(get_uca_structure_ids(cur))
