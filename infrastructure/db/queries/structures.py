"""Query services pour les structures, relations et formes de noms."""

from typing import Any


async def list_structures_async(
    cur: Any, *, type_filter: str | None, search: str
) -> list[dict[str, Any]]:
    """Liste des structures, filtrable par type et recherche accent-insensible.

    Tri canonique par type (labo > universite > onr > chu > ecole > site
    > autres) puis nom.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if type_filter:
        conditions.append("s.structure_type::text = %s")
        params.append(type_filter)
    if search:
        conditions.append(
            "(unaccent(s.name) ILIKE unaccent(%s) OR s.acronym ILIKE %s OR s.code ILIKE %s)"
        )
        params.extend([f"%{search}%"] * 3)
    where = " AND ".join(conditions) if conditions else "TRUE"

    await cur.execute(
        f"""
        SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type
        FROM structures s
        WHERE {where}
        ORDER BY CASE s.structure_type::text
            WHEN 'labo' THEN 1
            WHEN 'universite' THEN 2
            WHEN 'onr' THEN 3
            WHEN 'chu' THEN 4
            WHEN 'ecole' THEN 5
            WHEN 'site' THEN 6
            ELSE 7
        END, s.name
        """,
        params,
    )
    return await cur.fetchall()


async def get_structure_detail_async(cur: Any, structure_id: int) -> dict[str, Any] | None:
    """Détail complet : structure + parents + enfants + formes de noms.

    Retourne `None` si la structure n'existe pas (caller = 404).
    """
    await cur.execute(
        """
        SELECT id, code, name, acronym, structure_type::text AS type,
               ror_id, rnsr_id, hal_collection, api_ids
        FROM structures WHERE id = %s
        """,
        (structure_id,),
    )
    structure = await cur.fetchone()
    if not structure:
        return None

    await cur.execute(
        """
        SELECT sr.id AS relation_id, sr.relation_type::text,
               sp.id, sp.code, sp.name, sp.acronym, sp.structure_type::text AS type
        FROM structure_relations sr
        JOIN structures sp ON sp.id = sr.parent_id
        WHERE sr.child_id = %s
        ORDER BY sr.relation_type, sp.name
        """,
        (structure_id,),
    )
    parents = await cur.fetchall()

    await cur.execute(
        """
        SELECT sr.id AS relation_id, sr.relation_type::text,
               sc.id, sc.code, sc.name, sc.acronym, sc.structure_type::text AS type
        FROM structure_relations sr
        JOIN structures sc ON sc.id = sr.child_id
        WHERE sr.parent_id = %s
        ORDER BY sr.relation_type, sc.name
        """,
        (structure_id,),
    )
    children = await cur.fetchall()

    await cur.execute(
        """
        SELECT * FROM structure_name_forms
        WHERE structure_id = %s
        ORDER BY form_text
        """,
        (structure_id,),
    )
    forms = await cur.fetchall()

    return {
        "structure": structure,
        "parents": parents,
        "children": children,
        "forms": forms,
    }


async def get_name_form_async(cur: Any, form_id: int) -> dict[str, Any] | None:
    """Forme de nom par id. None si absente."""
    await cur.execute("SELECT * FROM structure_name_forms WHERE id = %s", (form_id,))
    return await cur.fetchone()
