"""Calcul des périmètres de structures.

Lit les périmètres depuis la table `perimeters` (colonne structure_ids).
Chaque structure racine inclut récursivement ses sous-structures
(via est_tutelle_de dans structure_relations).

L'association phase→périmètre est lue depuis la table `config` :
- perimeter_affiliations : périmètre pour la résolution des affiliations
- perimeter_persons : périmètre pour la création des personnes
"""


def get_perimeter_structure_ids(cur, perimeter_code: str) -> set[int]:
    """Retourne l'ensemble des structure_ids pour un périmètre donné.

    Chaque structure listée dans perimeters.structure_ids est une racine.
    Ses descendants récursifs (via est_tutelle_de) sont inclus.
    """
    cur.execute(
        "SELECT structure_ids FROM perimeters WHERE code = %s",
        (perimeter_code,))
    row = cur.fetchone()

    if not row:
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


# ── Fonctions par rôle (lisent la config) ──

def _config_perimeter_code(cur, config_key: str, default: str) -> str:
    """Lit un code périmètre depuis la table config."""
    try:
        cur.execute("SELECT value FROM config WHERE key = %s", (config_key,))
        row = cur.fetchone()
        if row:
            val = row["value"] if isinstance(row, dict) else row[0]
            # value est du JSONB, donc déjà désérialisé (str)
            return val if isinstance(val, str) else default
    except Exception:
        pass
    return default


def get_affiliations_structure_ids(cur) -> set[int]:
    """Périmètre pour la résolution des affiliations (structure_ids)."""
    code = _config_perimeter_code(cur, "perimeter_affiliations", "uca_wide")
    return get_perimeter_structure_ids(cur, code)


def get_persons_structure_ids(cur) -> set[int]:
    """Périmètre pour la création des personnes (in_perimeter)."""
    code = _config_perimeter_code(cur, "perimeter_persons", "uca")
    return get_perimeter_structure_ids(cur, code)


def get_persons_structure_ids_list(cur) -> list[int]:
    """Variante liste (pour usage dans les requêtes SQL ANY(%s))."""
    return list(get_persons_structure_ids(cur))


