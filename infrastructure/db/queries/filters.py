"""Fragments SQL et constructeurs de filtres pour les requêtes de lecture.

Ce module expose deux API en cohabitation pendant le chantier
sqlalchemy-core-adoption :

- **API legacy `apply_*`** : mute des listes `(conditions, params)` en
  parallèle, à exécuter via un curseur psycopg avec `%s` positionnels.
- **API SA `*_clause`** : retourne un `WhereClause | None`, composable
  via `assemble_where(...)`. Les fragments utilisent la syntaxe nommée
  SQLAlchemy `:nom` et s'exécutent uniquement via une `AsyncConnection`
  SA (incompatible avec psycopg cur).

Les call sites migrent un par un vers l'API SA. La branche legacy
disparaîtra en Phase 4.

Vit dans `infrastructure/` parce que ces fonctions génèrent du SQL
(infrastructure technique).
"""

from dataclasses import dataclass
from typing import Any

OA_OPEN_STATUSES = ("gold", "hybrid", "bronze", "green", "diamond")
OA_CLOSED_STATUSES = ("closed", "unknown")


def _sql_list(values: tuple[str, ...]) -> str:
    """Formate un tuple de strings en liste SQL littérale `('a','b',...)`.

    Utilisé pour injecter une liste de valeurs métier stables (constantes)
    dans du SQL inline. Ne pas utiliser avec des valeurs utilisateur.
    """
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


OA_OPEN_SQL = _sql_list(OA_OPEN_STATUSES)
OA_CLOSED_SQL = _sql_list(OA_CLOSED_STATUSES)

# Filtre SQL : la publication a au moins un authorship dans le périmètre.
# Exclut les peer_review et les personnes rejetées (fausses entités).
PUB_IS_UCA = """(
    EXISTS (SELECT 1 FROM authorships a
            JOIN persons pe ON pe.id = a.person_id AND pe.rejected = FALSE
            WHERE a.publication_id = p.id AND a.in_perimeter = TRUE)
    AND p.doc_type NOT IN ('peer_review', 'memoir')
)"""


def apply_access_filter(conditions: list, params: list, access: str | None) -> None:
    """Ajoute le filtre accès ouvert/fermé."""
    if not access:
        return
    if access == "open":
        conditions.append("p.oa_status::text = ANY(%s)")
        params.append(list(OA_OPEN_STATUSES))
    elif access == "closed":
        conditions.append(f"(p.oa_status::text IN {OA_CLOSED_SQL} OR p.oa_status IS NULL)")


def apply_oa_filter(conditions: list, params: list, oa_status: str | None) -> None:
    """Ajoute le filtre OA status aux conditions SQL."""
    if not oa_status:
        return
    values = [v.strip() for v in oa_status.split(",") if v.strip()]
    if not values:
        return
    expanded: list[str] = []
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


def apply_lab_filter(conditions: list, params: list, lab_ids: list[int]) -> None:
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


def apply_year_filter(conditions: list, params: list, years: list[int]) -> None:
    """Ajoute le filtre année (une ou plusieurs)."""
    if not years:
        return
    conditions.append("p.pub_year = ANY(%s)")
    params.append(years)


def apply_doc_type_filter(conditions: list, params: list, doc_types: list[str]) -> None:
    """Ajoute le filtre type de document."""
    if not doc_types:
        return
    conditions.append("p.doc_type::text = ANY(%s)")
    params.append(doc_types)


def apply_source_filter(conditions: list, source_values: list[str]) -> None:
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


def apply_person_filter(conditions: list, params: list, person_id: int) -> None:
    """Ajoute le filtre personne — uniquement les publications où la personne est auteur."""
    conditions.append("""
        EXISTS (SELECT 1 FROM authorships a
                JOIN source_authorships sa ON sa.authorship_id = a.id
                WHERE a.publication_id = p.id AND a.person_id = %s
                  AND NOT a.excluded
                  AND sa.roles && ARRAY['author']::text[])
    """)
    params.append(person_id)


def apply_corresponding_filter(
    conditions: list, params: list, person_id: int, corr_filter: str
) -> None:
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


# Fragments SQL réutilisés par apply_hal_status_filter
_SQL_HAS_HAL = (
    "EXISTS (SELECT 1 FROM source_publications sd "
    "WHERE sd.publication_id = p.id AND sd.source = 'hal')"
)
_SQL_IN_COLLECTION = (
    "EXISTS (SELECT 1 FROM source_publications sd "
    "WHERE sd.publication_id = p.id AND sd.source = 'hal' "
    "AND sd.hal_collections @> ARRAY[%s])"
)


def _build_hal_status_part(value: str, lab_hal_col: str | None, params: list) -> str | None:
    """Construit la clause SQL pour une valeur hal_status donnée.
    Retourne None si la valeur n'est pas applicable (ex: "notice" sans collection)."""
    if value == "hors_hal":
        return f"NOT {_SQL_HAS_HAL}"
    if value == "hors_collection":
        if lab_hal_col is None:
            return _SQL_HAS_HAL
        # « hors_collection » = au moins une entrée HAL ET aucune dans la
        # collection. Sans cette mutual exclusion, une publi avec plusieurs
        # dépôts HAL (cas réel — ex publi 24447 / collection CMH) tomberait
        # à la fois dans hors_collection et dans ok/notice.
        params.append(lab_hal_col)
        return (
            f"({_SQL_HAS_HAL} "
            "AND NOT EXISTS (SELECT 1 FROM source_publications sd "
            "WHERE sd.publication_id = p.id AND sd.source = 'hal' "
            "AND sd.hal_collections @> ARRAY[%s]))"
        )
    if value == "notice" and lab_hal_col is not None:
        params.append(lab_hal_col)
        return (
            f"({_SQL_IN_COLLECTION} "
            f"AND (p.oa_status IS NULL OR p.oa_status::text IN {OA_CLOSED_SQL}))"
        )
    if value == "ok" and lab_hal_col is not None:
        params.append(lab_hal_col)
        return (
            f"({_SQL_IN_COLLECTION} "
            f"AND p.oa_status IS NOT NULL AND p.oa_status::text NOT IN {OA_CLOSED_SQL})"
        )
    return None


def apply_hal_status_filter(
    conditions: list, params: list, values: list[str], lab_hal_col: str | None
) -> None:
    """Filtre sur l'état d'une publication dans HAL, par rapport à la collection
    d'un labo donné.

    Valeurs possibles dans `values` :
      - "hors_hal"         : pas de source HAL (ne nécessite pas lab_hal_col)
      - "hors_collection"  : dans HAL mais hors de la collection (ou dans HAL si
                             lab_hal_col est None, car aucune collection de référence)
      - "notice"           : dans la collection mais OA fermé/inconnu (nécessite lab_hal_col)
      - "ok"               : dans la collection ET OA ouvert (nécessite lab_hal_col)

    No-op si `values` est vide. Les valeurs qui requièrent lab_hal_col sont
    silencieusement ignorées quand il est None.
    """
    if not values:
        return
    parts = [p for v in values if (p := _build_hal_status_part(v, lab_hal_col, params))]
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
    parts: list[str] = []
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


# ── Filtres "persons" (listes de personnes) ──────────────────────


def apply_person_has_identifier_filter(conditions: list, id_type: str, value: str) -> None:
    """Filtre : la personne a-t-elle un identifiant donné (orcid, idhal, idref)
    avec un statut différent de 'rejected' ?

    `value` : "yes" pour présent, "no" pour absent, autre/vide → no-op.
    Utilisé dans `list_persons` et `get_laboratory_persons`.
    """
    if value == "yes":
        conditions.append(
            f"""EXISTS (
                SELECT 1 FROM person_identifiers pi
                WHERE pi.person_id = p.id
                  AND pi.id_type = '{id_type}'
                  AND pi.status != 'rejected'
            )"""
        )
    elif value == "no":
        conditions.append(
            f"""NOT EXISTS (
                SELECT 1 FROM person_identifiers pi
                WHERE pi.person_id = p.id
                  AND pi.id_type = '{id_type}'
                  AND pi.status != 'rejected'
            )"""
        )


def apply_person_linked_filter(conditions: list, value: str) -> None:
    """Filtre : la personne est-elle liée à au moins une authorship ?

    `value` : "yes" / "no" / autre (no-op).
    """
    if value == "yes":
        conditions.append("EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)")
    elif value == "no":
        conditions.append("NOT EXISTS (SELECT 1 FROM authorships a WHERE a.person_id = p.id)")


def apply_person_has_rh_filter(conditions: list, value: str) -> None:
    """Filtre : la personne a-t-elle une fiche RH (persons_rh) ?

    Suppose que la requête contient déjà `LEFT JOIN persons_rh prh ON ...`.
    `value` : "yes" / "no" / autre (no-op).
    """
    if value == "yes":
        conditions.append("prh.id IS NOT NULL")
    elif value == "no":
        conditions.append("prh.id IS NULL")


def apply_publisher_journal_filter(
    conditions: list, params: list, publisher_id: int | None, journal_id: int | None
) -> None:
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


# ── API SA Core composable (chantier sqlalchemy-core, Phase 1) ────


@dataclass(frozen=True)
class WhereClause:
    """Fragment SQL avec ses bind params nommés (syntaxe `:nom`).

    À assembler via `assemble_where(...)` puis exécuter via une
    `AsyncConnection` SA. Incompatible avec un curseur psycopg.
    """

    sql: str
    binds: dict[str, Any]


def assemble_where(clauses: list[WhereClause | None]) -> tuple[str, dict[str, Any]]:
    """Assemble les fragments en un `WHERE ...` SQL + dict de binds.

    Retourne `("TRUE", {})` si aucune clause valide, ce qui permet au
    caller d'écrire `f"WHERE {where_sql}"` sans cas particulier.
    """
    valid = [c for c in clauses if c is not None]
    if not valid:
        return "TRUE", {}
    sql = " AND ".join(c.sql for c in valid)
    binds: dict[str, Any] = {}
    for c in valid:
        binds.update(c.binds)
    return sql, binds


def year_clause(years: list[int]) -> WhereClause | None:
    if not years:
        return None
    return WhereClause("p.pub_year = ANY(:flt_years)", {"flt_years": years})


def lab_clause(lab_ids: list[int]) -> WhereClause | None:
    if not lab_ids:
        return None
    return WhereClause(
        """EXISTS (
            SELECT 1 FROM authorships a
            WHERE a.publication_id = p.id
              AND a.structure_ids && CAST(:flt_lab_ids AS int[])
              AND NOT a.excluded
        )""",
        {"flt_lab_ids": lab_ids},
    )


def oa_clause(oa_status: str | None) -> WhereClause | None:
    if not oa_status:
        return None
    values = [v.strip() for v in oa_status.split(",") if v.strip()]
    if not values:
        return None
    expanded: list[str] = []
    for v in values:
        if v == "oa":
            expanded.extend(OA_OPEN_STATUSES)
        else:
            expanded.append(v)
    expanded = list(set(expanded))
    if len(expanded) == 1:
        return WhereClause("p.oa_status::text = :flt_oa_status", {"flt_oa_status": expanded[0]})
    return WhereClause("p.oa_status::text = ANY(:flt_oa_status)", {"flt_oa_status": expanded})


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
    # Typing mypy : la signature Any du key n'est pas garantie, on cast
    return SORT_MAP.get(sort, SORT_MAP["name"])
