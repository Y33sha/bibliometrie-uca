"""Query services pour le tableau de bord admin de feedback détection d'adresses."""

from typing import Any


async def feedback_structures_async(cur: Any, types: list[str]) -> list[dict[str, Any]]:
    """Structures éligibles au tableau de bord feedback, filtrées par type."""
    await cur.execute(
        """
        SELECT s.id, s.code, s.name, s.acronym,
               s.structure_type::text AS type
        FROM structures s
        WHERE s.structure_type::text = ANY(%s)
        ORDER BY s.name
        """,
        (types,),
    )
    return await cur.fetchall()


async def feedback_stats_async(cur: Any, structure_id: int) -> dict[str, Any]:
    """Compteurs bruts (concordances, FN, FP, pending) pour une structure.

    Retourne un dict avec les colonnes brutes — la dérivation (taux,
    total reviewed) est faite par le caller.
    """
    await cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE is_confirmed IS NOT NULL) AS total_reviewed,
            COUNT(*) FILTER (WHERE is_confirmed = TRUE AND matched_form_id IS NOT NULL) AS concordant_valid,
            COUNT(*) FILTER (WHERE is_confirmed = FALSE AND matched_form_id IS NULL) AS concordant_rejected,
            COUNT(*) FILTER (WHERE is_confirmed = TRUE AND matched_form_id IS NULL) AS false_negatives,
            COUNT(*) FILTER (WHERE is_confirmed = FALSE AND matched_form_id IS NOT NULL) AS false_positives,
            COUNT(*) FILTER (WHERE is_confirmed IS NULL AND matched_form_id IS NOT NULL) AS pending
        FROM address_structures
        WHERE structure_id = %s
        """,
        (structure_id,),
    )
    return await cur.fetchone()


async def feedback_false_negatives_async(
    cur: Any, *, structure_id: int, page: int, per_page: int, search: str
) -> dict[str, Any]:
    """Adresses confirmées manuellement mais non détectées par le script."""
    return await _feedback_paginated(
        cur,
        structure_id=structure_id,
        page=page,
        per_page=per_page,
        search=search,
        kind_where="ast.is_confirmed = TRUE AND ast.matched_form_id IS NULL",
        with_matched_forms=False,
    )


async def feedback_false_positives_async(
    cur: Any, *, structure_id: int, page: int, per_page: int, search: str
) -> dict[str, Any]:
    """Adresses détectées mais rejetées manuellement (avec les formes matchées)."""
    return await _feedback_paginated(
        cur,
        structure_id=structure_id,
        page=page,
        per_page=per_page,
        search=search,
        kind_where="ast.is_confirmed = FALSE AND ast.matched_form_id IS NOT NULL",
        with_matched_forms=True,
    )


async def _feedback_paginated(
    cur: Any,
    *,
    structure_id: int,
    page: int,
    per_page: int,
    search: str,
    kind_where: str,
    with_matched_forms: bool,
) -> dict[str, Any]:
    """Backbone partagé FN/FP : count + select paginé.

    `kind_where` filtre la nature du feedback (FN vs FP). `with_matched_forms`
    ajoute la sous-requête json_agg des formes matchées (utile pour FP afin
    d'identifier la forme à corriger).
    """
    offset = (page - 1) * per_page
    conditions = ["ast.structure_id = %s", kind_where]
    params: list[Any] = [structure_id]
    if search:
        conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
        params.append(f"%{search}%")
    where = " AND ".join(conditions)

    await cur.execute(
        f"""
        SELECT COUNT(*)
        FROM address_structures ast
        JOIN addresses a ON a.id = ast.address_id
        WHERE {where}
        """,
        params,
    )
    total = (await cur.fetchone())["count"]

    matched_forms_select = (
        ""
        if not with_matched_forms
        else """,
            (SELECT json_agg(json_build_object(
                'form_id', nf.id,
                'form_text', nf.form_text,
                'requires_context_of', nf.requires_context_of,
                'structure_name', COALESCE(s.acronym, s.name)
            ))
            FROM address_structures ast2
            JOIN structure_name_forms nf ON nf.id = ast2.matched_form_id
            JOIN structures s ON s.id = nf.structure_id
            WHERE ast2.address_id = a.id
              AND ast2.structure_id = %s
              AND ast2.matched_form_id IS NOT NULL
            ) AS matched_forms"""
    )
    # Si on inclut matched_forms, son `structure_id` placeholder précède
    # ceux du WHERE — d'où l'ordre `[structure_id] + params + ...`.
    select_params = (
        [structure_id] + params + [per_page, offset]
        if with_matched_forms
        else params + [per_page, offset]
    )

    await cur.execute(
        f"""
        SELECT
            a.id, a.raw_text, a.pub_count,
            (SELECT json_agg(json_build_object(
                'structure_id', s.id, 'acronym', s.acronym, 'name', s.name,
                'is_detected', (ast2.matched_form_id IS NOT NULL),
                'is_confirmed', ast2.is_confirmed
            ))
            FROM address_structures ast2
            JOIN structures s ON s.id = ast2.structure_id
            WHERE ast2.address_id = a.id AND s.structure_type != 'site'
            ) AS labs{matched_forms_select}
        FROM address_structures ast
        JOIN addresses a ON a.id = ast.address_id
        WHERE {where}
        ORDER BY a.pub_count DESC, a.id
        LIMIT %s OFFSET %s
        """,
        select_params,
    )

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "addresses": await cur.fetchall(),
    }
