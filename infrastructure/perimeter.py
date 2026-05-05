from typing import Any

"""Calcul des périmètres de structures.

Lit les périmètres depuis la table `perimeters` (colonne structure_ids).
Chaque structure racine inclut récursivement ses sous-structures
(via est_tutelle_de dans structure_relations).

L'association phase→périmètre est lue depuis la table `config` :
- perimeter_affiliations : périmètre pour la résolution des affiliations
- perimeter_persons : périmètre pour la création des personnes
"""


def get_perimeter_structure_ids(cur: Any, perimeter_code: str) -> set[int]:
    """Retourne l'ensemble des structure_ids pour un périmètre donné.

    Chaque structure listée dans perimeters.structure_ids est une racine.
    Ses descendants récursifs (via est_tutelle_de) sont inclus.
    """
    cur.execute("SELECT structure_ids FROM perimeters WHERE code = %s", (perimeter_code,))
    row = cur.fetchone()

    if not row:
        return set()

    root_ids = row["structure_ids"] if isinstance(row, dict) else row[0]
    if not root_ids:
        return set()

    # Résoudre les descendants récursifs en une seule requête
    cur.execute(
        """
        WITH RECURSIVE descendants AS (
            SELECT unnest(%s::int[]) AS id
            UNION
            SELECT sr.child_id FROM structure_relations sr
            JOIN descendants d ON d.id = sr.parent_id
            WHERE sr.relation_type = 'est_tutelle_de'
        )
        SELECT id FROM descendants
    """,
        (root_ids,),
    )

    return {r["id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()}


# ── Fonctions par rôle (lisent la config) ──


def _config_perimeter_code(cur: Any, config_key: str, default: str) -> str:
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


def get_affiliations_structure_ids(cur: Any) -> set[int]:
    """Périmètre pour la résolution des affiliations (structure_ids)."""
    code = _config_perimeter_code(cur, "perimeter_affiliations", "uca_wide")
    return get_perimeter_structure_ids(cur, code)


def get_persons_structure_ids(cur: Any) -> set[int]:
    """Périmètre pour la création des personnes (in_perimeter)."""
    code = _config_perimeter_code(cur, "perimeter_persons", "uca")
    return get_perimeter_structure_ids(cur, code)


def get_persons_structure_ids_list(cur: Any) -> list[int]:
    """Variante liste (pour usage dans les requêtes SQL ANY(%s))."""
    return list(get_persons_structure_ids(cur))


# ── Variantes async — utilisées par la surface FastAPI ────────────


async def async_get_perimeter_structure_ids(cur: Any, perimeter_code: str) -> set[int]:
    """Variante async de get_perimeter_structure_ids."""
    await cur.execute("SELECT structure_ids FROM perimeters WHERE code = %s", (perimeter_code,))
    row = await cur.fetchone()

    if not row:
        return set()

    root_ids = row["structure_ids"] if isinstance(row, dict) else row[0]
    if not root_ids:
        return set()

    await cur.execute(
        """
        WITH RECURSIVE descendants AS (
            SELECT unnest(%s::int[]) AS id
            UNION
            SELECT sr.child_id FROM structure_relations sr
            JOIN descendants d ON d.id = sr.parent_id
            WHERE sr.relation_type = 'est_tutelle_de'
        )
        SELECT id FROM descendants
    """,
        (root_ids,),
    )
    rows = await cur.fetchall()
    return {r["id"] if isinstance(r, dict) else r[0] for r in rows}


async def _async_config_perimeter_code(cur: Any, config_key: str, default: str) -> str:
    """Variante async de _config_perimeter_code."""
    try:
        await cur.execute("SELECT value FROM config WHERE key = %s", (config_key,))
        row = await cur.fetchone()
        if row:
            val = row["value"] if isinstance(row, dict) else row[0]
            return val if isinstance(val, str) else default
    except Exception:
        pass
    return default


async def async_get_persons_structure_ids(cur: Any) -> set[int]:
    """Variante async de get_persons_structure_ids."""
    code = await _async_config_perimeter_code(cur, "perimeter_persons", "uca")
    return await async_get_perimeter_structure_ids(cur, code)


async def async_get_persons_structure_ids_list(cur: Any) -> list[int]:
    """Variante async liste (pour ANY(%s))."""
    return list(await async_get_persons_structure_ids(cur))


async def async_get_persons_perimeter_root_ids(cur: Any) -> list[int]:
    """Racines (entrées déclaratives de `perimeters.structure_ids`) du périmètre
    "persons", sans expansion par `est_tutelle_de`.

    À distinguer de `async_get_persons_structure_ids(cur)` qui retourne la
    clôture transitive : les racines + tous les labos descendants. Utilisé
    quand un code appelant veut filtrer explicitement les racines du périmètre
    (ex. exclure l'UCA des tutelles affichées pour un labo).
    """
    code = await _async_config_perimeter_code(cur, "perimeter_persons", "uca")
    await cur.execute("SELECT structure_ids FROM perimeters WHERE code = %s", (code,))
    row = await cur.fetchone()
    if not row:
        return []
    ids = row["structure_ids"] if isinstance(row, dict) else row[0]
    return list(ids) if ids else []
