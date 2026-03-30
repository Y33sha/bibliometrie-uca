"""Shared SQL filter helpers and constants."""


OA_OPEN_STATUSES = ('gold', 'hybrid', 'bronze', 'green')

# Filtre SQL : la publication a au moins un authorship UCA.
# Exclut les peer_review (reviews anonymes, auteurs = auteurs de l'article reviewé, pas du review).
PUB_IS_UCA = """(
    EXISTS (SELECT 1 FROM authorships a
            WHERE a.publication_id = p.id AND a.is_uca = TRUE)
    AND p.doc_type != 'peer_review'
)"""


def apply_oa_filter(conditions: list, params: list, oa_status: str | None):
    """Ajoute le filtre OA status aux conditions SQL."""
    if not oa_status:
        return
    values = [v.strip() for v in oa_status.split(',') if v.strip()]
    if not values:
        return
    expanded = []
    for v in values:
        if v == 'oa':
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
    """Ajoute les filtres de source (hal_yes, hal_no, oa_yes, oa_no, wos_yes, wos_no)."""
    SOURCE_MAP = {
        "hal": "hal",
        "oa": "openalex",
        "wos": "wos",
    }
    for sv in source_values:
        parts = sv.rsplit("_", 1)
        if len(parts) != 2:
            continue
        prefix, mode = parts
        source = SOURCE_MAP.get(prefix)
        if not source or mode not in ("yes", "no"):
            continue
        op = "EXISTS" if mode == "yes" else "NOT EXISTS"
        conditions.append(
            f"{op} (SELECT 1 FROM publication_sources ps"
            f" WHERE ps.publication_id = p.id AND ps.source = '{source}')"
        )


def apply_person_filter(conditions: list, params: list, person_id: int):
    """Ajoute le filtre personne via la table de vérité."""
    conditions.append(
        "EXISTS (SELECT 1 FROM authorships a WHERE a.publication_id = p.id AND a.person_id = %s AND NOT a.excluded)"
    )
    params.append(person_id)


def apply_corresponding_filter(conditions: list, params: list,
                                person_id: int, corr_filter: str):
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


def apply_publisher_journal_filter(conditions: list, params: list,
                                   publisher_id: int | None, journal_id: int | None):
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
    return [int(v) for v in s.split(',') if v.strip()] if s else []


def parse_str_csv(s: str) -> list[str]:
    """Parse une chaîne CSV de strings."""
    return [v.strip() for v in s.split(',') if v.strip()] if s else []


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
