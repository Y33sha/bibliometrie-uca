"""Shared SQL filter helpers and constants."""

OA_OPEN_STATUSES = ("gold", "hybrid", "bronze", "green", "diamond")

# Filtre SQL : la publication a au moins un authorship dans le périmètre.
# Exclut les peer_review et les personnes rejetées (fausses entités).
PUB_IS_UCA = """(
    EXISTS (SELECT 1 FROM authorships a
            JOIN persons pe ON pe.id = a.person_id AND pe.rejected = FALSE
            WHERE a.publication_id = p.id AND a.in_perimeter = TRUE)
    AND p.doc_type NOT IN ('peer_review', 'memoir')
)"""


def apply_access_filter(conditions: list, params: list, access: str | None):
    """Ajoute le filtre accès ouvert/fermé."""
    if not access:
        return
    if access == "open":
        conditions.append("p.oa_status::text = ANY(%s)")
        params.append(list(OA_OPEN_STATUSES))
    elif access == "closed":
        conditions.append(
            "(p.oa_status::text = 'closed' OR p.oa_status IS NULL OR p.oa_status::text = 'unknown')"
        )


def apply_oa_filter(conditions: list, params: list, oa_status: str | None):
    """Ajoute le filtre OA status aux conditions SQL."""
    if not oa_status:
        return
    values = [v.strip() for v in oa_status.split(",") if v.strip()]
    if not values:
        return
    expanded = []
    for v in values:
        if v == "oa":
            expanded.extend(OA_OPEN_STATUSES)
        else:
            expanded.append(v)
    expanded = list(set(expanded))
    if len(expanded) == 1:
        conditions.append("p.oa_status::text = %s")
        params.append(expanded[0])
    else:
        conditions.append("p.oa_status::text = ANY(%s)")
        params.append(expanded)


def apply_lab_filter(conditions: list, params: list, lab_ids: list[int]):
    """Ajoute le filtre laboratoire via la table de vérité authorships."""
    if not lab_ids:
        return
    conditions.append("""
        EXISTS (
            SELECT 1 FROM authorships a
            WHERE a.publication_id = p.id
              AND a.structure_ids && %s::int[]
              AND NOT a.excluded
        )
    """)
    params.append(lab_ids)


def apply_year_filter(conditions: list, params: list, years: list[int]):
    """Ajoute le filtre année (une ou plusieurs)."""
    if not years:
        return
    conditions.append("p.pub_year = ANY(%s)")
    params.append(years)


def apply_doc_type_filter(conditions: list, params: list, doc_types: list[str]):
    """Ajoute le filtre type de document."""
    if not doc_types:
        return
    conditions.append("p.doc_type::text = ANY(%s)")
    params.append(doc_types)


def apply_source_filter(conditions: list, source_values: list[str]):
    """Ajoute les filtres de source via la colonne publications.sources (GIN)."""
    SOURCE_MAP = {
        "hal": "hal",
        "oa": "openalex",
        "scanr": "scanr",
        "wos": "wos",
        "theses": "theses",
    }
    for sv in source_values:
        parts = sv.rsplit("_", 1)
        if len(parts) != 2:
            continue
        prefix, mode = parts
        source = SOURCE_MAP.get(prefix)
        if not source or mode not in ("yes", "no"):
            continue
        if mode == "yes":
            conditions.append(f"p.sources @> ARRAY['{source}'::source_type]")
        else:
            conditions.append(f"NOT p.sources @> ARRAY['{source}'::source_type]")


def apply_person_filter(conditions: list, params: list, person_id: int):
    """Ajoute le filtre personne — uniquement les publications où la personne est auteur."""
    conditions.append("""
        EXISTS (SELECT 1 FROM authorships a
                JOIN source_authorships sa ON sa.authorship_id = a.id
                WHERE a.publication_id = p.id AND a.person_id = %s
                  AND NOT a.excluded
                  AND sa.roles && ARRAY['author']::text[])
    """)
    params.append(person_id)


def apply_corresponding_filter(conditions: list, params: list, person_id: int, corr_filter: str):
    """Filtre sur is_corresponding pour une personne donnée."""
    if not corr_filter or not person_id:
        return
    if corr_filter == "yes":
        conditions.append("""
            EXISTS (SELECT 1 FROM authorships a
                    WHERE a.publication_id = p.id AND a.person_id = %s
                      AND a.is_corresponding = TRUE AND NOT a.excluded)
        """)
        params.append(person_id)
    elif corr_filter == "no":
        conditions.append("""
            NOT EXISTS (SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = %s
                          AND a.is_corresponding = TRUE AND NOT a.excluded)
        """)
        params.append(person_id)


def apply_hal_status_filter(
    conditions: list, params: list, values: list[str], lab_hal_col: str | None
) -> None:
    """Filtre sur l'état d'une publication dans HAL, par rapport à la collection
    d'un labo donné.

    Valeurs possibles dans `values` :
      - "hors_hal"         : la publication n'a pas de source HAL
      - "hors_collection"  : présente dans HAL mais hors de la collection du labo
      - "notice"           : dans la collection mais OA fermé/inconnu (simple notice)
      - "ok"               : dans la collection ET OA ouvert

    No-op si `values` est vide ou `lab_hal_col` est None.
    """
    if not values or not lab_hal_col:
        return
    parts = []
    for v in values:
        if v == "hors_hal":
            parts.append(
                "NOT EXISTS (SELECT 1 FROM source_publications sd "
                "WHERE sd.publication_id = p.id AND sd.source = 'hal')"
            )
        elif v == "hors_collection":
            parts.append(
                "EXISTS (SELECT 1 FROM source_publications sd "
                "WHERE sd.publication_id = p.id AND sd.source = 'hal' "
                "AND (sd.hal_collections IS NULL OR NOT sd.hal_collections @> ARRAY[%s]))"
            )
            params.append(lab_hal_col)
        elif v == "notice":
            parts.append(
                "(EXISTS (SELECT 1 FROM source_publications sd "
                "WHERE sd.publication_id = p.id AND sd.source = 'hal' "
                "AND sd.hal_collections @> ARRAY[%s]) "
                "AND (p.oa_status IS NULL OR p.oa_status::text IN ('closed', 'unknown')))"
            )
            params.append(lab_hal_col)
        elif v == "ok":
            parts.append(
                "(EXISTS (SELECT 1 FROM source_publications sd "
                "WHERE sd.publication_id = p.id AND sd.source = 'hal' "
                "AND sd.hal_collections @> ARRAY[%s]) "
                "AND p.oa_status IS NOT NULL "
                "AND p.oa_status::text NOT IN ('closed', 'unknown'))"
            )
            params.append(lab_hal_col)
    if len(parts) == 1:
        conditions.append(parts[0])
    elif len(parts) > 1:
        conditions.append("(" + " OR ".join(parts) + ")")


def apply_apc_filter(
    conditions: list,
    params: list,
    has_apc: str,
    root_structure_id: int,
    lab_ids: list[int] | None = None,
) -> None:
    """Filtre sur l'existence et le payeur des frais APC (Article Processing Charges).

    Valeurs possibles dans `has_apc` (CSV, ex: "uca,none") :
      - "uca"       : payé par un budget UCA (racine du périmètre)
      - "non_uca"   : payé hors UCA (mais des APC existent)
      - "other"     : alias de "non_uca" (ancien nom)
      - "none"      : aucun APC enregistré
      - "this_lab"  : payé par le labo sélectionné (nécessite lab_ids)
      - "other_uca" : payé par UCA mais pas par ce labo (nécessite lab_ids)
    """
    if not has_apc:
        return
    lab_ids = lab_ids or []
    apc_map = {
        "uca": (
            "EXISTS (SELECT 1 FROM apc_payments ap "
            "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s)",
            1,
        ),
        "other": (
            "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) "
            "AND NOT EXISTS (SELECT 1 FROM apc_payments ap "
            "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s))",
            1,
        ),
        "non_uca": (
            "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) "
            "AND NOT EXISTS (SELECT 1 FROM apc_payments ap "
            "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s))",
            1,
        ),
        "none": (
            "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
            0,
        ),
    }
    parts = []
    for v in [x.strip() for x in has_apc.split(",") if x.strip()]:
        if v in apc_map:
            sql, rid_count = apc_map[v]
            parts.append(sql)
            params.extend([root_structure_id] * rid_count)
        elif v == "this_lab" and lab_ids:
            parts.append(
                "EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[]))"
            )
            params.append(lab_ids)
        elif v == "other_uca" and lab_ids:
            parts.append(
                "(EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s) "
                "AND NOT EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[])))"
            )
            params.extend([root_structure_id, lab_ids])
    if len(parts) == 1:
        conditions.append(parts[0])
    elif len(parts) > 1:
        conditions.append("(" + " OR ".join(parts) + ")")


def apply_in_perimeter_person_filter(
    conditions: list, params: list, in_perimeter: str, person_id: int | None
) -> None:
    """Filtre : la personne donnée a-t-elle un authorship in_perimeter sur la publication ?

    - in_perimeter = "yes" : au moins un authorship in_perimeter pour person_id
    - in_perimeter = "no"  : aucun authorship in_perimeter pour person_id
    - autre / vide         : no-op
    No-op aussi si person_id est None.
    """
    if not in_perimeter or not person_id:
        return
    negate = "" if in_perimeter == "yes" else "NOT "
    conditions.append(
        f"""
        {negate}EXISTS (SELECT 1 FROM authorships a
                WHERE a.publication_id = p.id AND a.person_id = %s
                  AND a.in_perimeter = TRUE AND NOT a.excluded)
    """
    )
    params.append(person_id)


def apply_no_lab_filter(conditions: list, params: list) -> None:
    """Filtre : la publication n'a aucun authorship rattaché à un labo du périmètre.
    Équivaut au filtre "lab_id=none" dans l'API.
    """
    conditions.append(
        """
        NOT EXISTS (
            SELECT 1 FROM authorships a
            JOIN structures s ON s.id = ANY(a.structure_ids)
            WHERE a.publication_id = p.id
              AND NOT a.excluded
              AND s.structure_type = 'labo'
        )
    """
    )


def apply_publisher_journal_filter(
    conditions: list, params: list, publisher_id: int | None, journal_id: int | None
):
    """Ajoute les filtres éditeur et revue."""
    if publisher_id:
        conditions.append("""
            EXISTS (SELECT 1 FROM journals j2
                    WHERE j2.id = p.journal_id AND j2.publisher_id = %s)
        """)
        params.append(publisher_id)
    if journal_id:
        conditions.append("p.journal_id = %s")
        params.append(journal_id)


def parse_int_csv(s: str) -> list[int]:
    """Parse une chaîne CSV d'entiers (ex: '1,2,3')."""
    return [int(v) for v in s.split(",") if v.strip()] if s else []


def parse_str_csv(s: str) -> list[str]:
    """Parse une chaîne CSV de strings."""
    return [v.strip() for v in s.split(",") if v.strip()] if s else []


def persons_sort_clause(sort: str) -> str:
    """Return an ORDER BY clause for the persons query."""
    SORT_MAP = {
        "name": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
        "-name": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
        "pubs": "pub_count ASC, LOWER(p.last_name) ASC",
        "-pubs": "pub_count DESC, LOWER(p.last_name) ASC",
        "dept": "prh.department_name ASC NULLS LAST, LOWER(p.last_name) ASC",
        "-dept": "prh.department_name DESC NULLS LAST, LOWER(p.last_name) ASC",
        "role": "prh.role_title ASC NULLS LAST, LOWER(p.last_name) ASC",
        "-role": "prh.role_title DESC NULLS LAST, LOWER(p.last_name) ASC",
    }
    return SORT_MAP.get(sort, SORT_MAP["name"])
