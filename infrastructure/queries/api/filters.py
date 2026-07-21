"""Fragments SQL et constructeurs de filtres pour les requêtes de lecture.

Chaque `*_clause(...)` retourne un `WhereClause | None`, composable via `assemble_where(...)`. Les fragments utilisent la syntaxe nommée SQLAlchemy `:nom` et s'exécutent via une `Connection` SA.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from domain.normalize import normalize_text
from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES
from domain.publications.metadata import ACCESS_LEVELS, OA_CLOSED_STATUSES, OA_OPEN_STATUSES


def _sql_list(values: Iterable[str]) -> str:
    """Formate un tuple de strings en liste SQL littérale `('a','b',...)`.

    Utilisé pour injecter une liste de valeurs métier stables (constantes)
    dans du SQL inline. Ne pas utiliser avec des valeurs utilisateur.
    """
    return "(" + ",".join(f"'{v}'" for v in sorted(values)) + ")"


OA_OPEN_SQL = _sql_list(OA_OPEN_STATUSES)
OA_CLOSED_SQL = _sql_list(OA_CLOSED_STATUSES)
PUBLIC_PERSON_IDENTIFIER_TYPES_SQL = _sql_list(PUBLIC_PERSON_IDENTIFIER_TYPES)

# Colonnes de ventilation OA par statut (alias `p` = publications), partagées par les
# requêtes stats (éditeurs/revues/labos/années). `embargoed` est rangé par rang, juste
# avant `closed`.
OA_BREAKDOWN_COLS_SQL = """
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'gold') AS gold,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'diamond') AS diamond,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'hybrid') AS hybrid,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'bronze') AS bronze,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'green') AS green,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'embargoed') AS embargoed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown') AS unknown""".strip()

# Buckets OA simplifiés pour les donuts dashboard (alias `p`) : open / embargo / closed /
# unknown + total. `open_access` exclut `embargoed` (compté à part) et les statuts fermés.
OA_DASHBOARD_COLS_SQL = f"""
            COUNT(DISTINCT p.id) FILTER (
                WHERE p.oa_status NOT IN {OA_CLOSED_SQL}
                  AND p.oa_status != 'embargoed' AND p.oa_status IS NOT NULL
            ) AS open_access,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'embargoed') AS embargoed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
            COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'unknown' OR p.oa_status IS NULL) AS unknown,
            COUNT(DISTINCT p.id) AS total""".strip()


def publication_in_perimeter(alias: str = "p") -> str:
    """Filtre SQL : la publication (table `publications` aliasée `alias`) est dans
    le périmètre.

    Lit le flag matérialisé `publications.in_perimeter` (= au moins un authorship
    in-perimeter d'une personne non rejetée), maintenu en phase `authorships`
    (`refresh_publications_in_perimeter`) et à l'action de rejet de personne.
    Filtre **par requête** : seules les listes scopées UCA l'appliquent ; les vues
    par personne montrent tout. `alias` paramètre l'alias appelant — nécessaire
    quand `p` est déjà pris (ex. le publisher dans `publishers.py`)."""
    return f"({alias}.in_perimeter)"


# La plupart des requêtes aliasent les publications `p` : constante de commodité.
PUBLICATION_IS_IN_PERIMETER = publication_in_perimeter()

# Un sujet dont l'usage global dépasse ce seuil est trop générique pour un nuage de mots :
# « research article » ou « science » arrivent en tête de tous les contextes et masquent ce
# qui distingue celui qu'on regarde.
GENERIC_SUBJECT_MAX_USAGE = 5000

# Filtre SQL : le sujet (table `subjects` aliasée `s`) n'est pas générique. Partagé par les
# quatre nuages de mots — éditeur, revue, laboratoire, personne — qui écartent le même ensemble.
SUBJECT_IS_NOT_GENERIC = f"(s.usage_count <= {GENERIC_SUBJECT_MAX_USAGE})"


@dataclass(frozen=True)
class WhereClause:
    """Fragment SQL avec ses bind params nommés (syntaxe `:nom`).

    À assembler via `assemble_where(...)` puis exécuter via une
    `Connection` SA. Incompatible avec un curseur psycopg.
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
            JOIN authorship_structures aus ON aus.authorship_id = a.id
            WHERE a.publication_id = p.id
              AND aus.structure_id = ANY(:flt_lab_ids)
        )""",
        {"flt_lab_ids": lab_ids},
    )


def oa_clause(oa_status: list[str]) -> WhereClause | None:
    if not oa_status:
        return None
    if len(oa_status) == 1:
        return WhereClause("p.oa_status::text = :flt_oa_status", {"flt_oa_status": oa_status[0]})
    return WhereClause("p.oa_status::text = ANY(:flt_oa_status)", {"flt_oa_status": oa_status})


def access_clause(access: list[str]) -> WhereClause | None:
    """Filtre par niveau d'accès, les niveaux demandés combinés en OR.

    Les niveaux ventilent les statuts OA (`ACCESS_LEVELS`) : filtrer sur un niveau revient à filtrer sur les statuts qu'il recouvre. Un `oa_status` nul compte comme fermé, la colonne ayant précédé la valeur `unknown`.
    """
    if not access:
        return None
    statuses = {s for level in access for s in ACCESS_LEVELS.get(level, frozenset())}
    include_null = "closed" in access
    if not statuses and not include_null:
        return None
    conditions: list[str] = []
    binds: dict[str, Any] = {}
    if statuses:
        conditions.append("p.oa_status::text = ANY(:flt_access_statuses)")
        binds["flt_access_statuses"] = sorted(statuses)
    if include_null:
        conditions.append("p.oa_status IS NULL")
    sql = conditions[0] if len(conditions) == 1 else "(" + " OR ".join(conditions) + ")"
    return WhereClause(sql, binds)


def doc_type_clause(doc_types: list[str]) -> WhereClause | None:
    if not doc_types:
        return None
    return WhereClause("p.doc_type::text = ANY(:flt_doc_types)", {"flt_doc_types": doc_types})


def excluded_doc_type_clause(excluded_types: list[str]) -> WhereClause | None:
    if not excluded_types:
        return None
    return WhereClause(
        "p.doc_type::text != ALL(:flt_excluded_types)", {"flt_excluded_types": excluded_types}
    )


def search_clause(search: str) -> WhereClause | None:
    """Recherche plein-texte : titre normalisé ou label de sujet.

    Partagée par la liste, l'export et les facettes pour que les trois comptent
    le même ensemble. Bind `:flt_search_pat`.
    """
    if not search:
        return None
    pattern = f"%{normalize_text(search)}%"
    return WhereClause(
        "(p.title_normalized ILIKE :flt_search_pat "
        "OR p.id IN (SELECT ps.publication_id FROM publication_subjects ps "
        "JOIN subjects s ON s.id = ps.subject_id "
        "WHERE normalize_name_form(s.label) ILIKE :flt_search_pat))",
        {"flt_search_pat": pattern},
    )


def person_search_clause(search: str) -> WhereClause | None:
    """Recherche annuaire : nom ou prénom (accent-insensible).

    Partagée par l'annuaire des personnes et ses facettes (mêmes résultats).
    Alias `p` = persons. Bind `:flt_person_search`.
    """
    if not search:
        return None
    return WhereClause(
        "(unaccent(p.last_name) ILIKE unaccent(:flt_person_search) "
        "OR unaccent(p.first_name) ILIKE unaccent(:flt_person_search))",
        {"flt_person_search": f"%{search}%"},
    )


def source_clause(source_values: list[str]) -> WhereClause | None:
    """Filtre source via publications.sources (GIN). `source_values` = liste
    `{prefix}_{yes|no}` (constantes côté front, sans bind nécessaire)."""
    SOURCE_MAP = {
        "hal": "hal",
        "oa": "openalex",
        "scanr": "scanr",
        "wos": "wos",
        "theses": "theses",
    }
    parts: list[str] = []
    for sv in source_values:
        bits = sv.rsplit("_", 1)
        if len(bits) != 2:
            continue
        prefix, mode = bits
        source = SOURCE_MAP.get(prefix)
        if not source or mode not in ("yes", "no"):
            continue
        if mode == "yes":
            parts.append(f"p.sources @> ARRAY['{source}'::source_type]")
        else:
            parts.append(f"NOT p.sources @> ARRAY['{source}'::source_type]")
    if not parts:
        return None
    return WhereClause(" AND ".join(parts), {})


def person_clause(person_id: int) -> WhereClause:
    """Filtre : la personne donnée est auteur (rôle 'author') de la publication."""
    return WhereClause(
        """EXISTS (SELECT 1 FROM authorships a
                WHERE a.publication_id = p.id AND a.person_id = :flt_person_id
                  AND a.roles && ARRAY['author']::text[])""",
        {"flt_person_id": person_id},
    )


def _person_toggle_clause(
    values: list[str], exists_sql: str, binds: dict[str, Any]
) -> WhereClause | None:
    """Facette binaire `yes`/`no` sur un prédicat EXISTS lié à une personne.

    `values` est une liste `yes`/`no` (multi-sélection côté front) : `yes` retient
    les publications vérifiant `exists_sql`, `no` les autres, combinés en OR. Cocher
    les deux ne pose donc aucune contrainte. Une valeur inconnue est ignorée.
    """
    parts: list[str] = []
    if "yes" in values:
        parts.append(exists_sql)
    if "no" in values:
        parts.append(f"NOT {exists_sql}")
    if not parts:
        return None
    sql = parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    return WhereClause(sql, binds)


def corresponding_clause(person_id: int, corr_filter: list[str]) -> WhereClause | None:
    if not corr_filter or not person_id:
        return None
    return _person_toggle_clause(
        corr_filter,
        """EXISTS (SELECT 1 FROM authorships a
                WHERE a.publication_id = p.id AND a.person_id = :flt_corr_person
                  AND a.is_corresponding = TRUE)""",
        {"flt_corr_person": person_id},
    )


_SQL_HAS_HAL_SA = (
    "EXISTS (SELECT 1 FROM source_publications sd "
    "WHERE sd.publication_id = p.id AND sd.source = 'hal')"
)
_SQL_IN_COLLECTION_SA = (
    "EXISTS (SELECT 1 FROM source_publications sd "
    "WHERE sd.publication_id = p.id AND sd.source = 'hal' "
    "AND sd.hal_collections @> ARRAY[:flt_hal_collection])"
)


def hal_status_clause(values: list[str], lab_hal_col: str | None) -> WhereClause | None:
    """Variante SA de `apply_hal_status_filter`. `:flt_hal_collection` est
    partagé entre les sous-clauses qui en ont besoin (valeur unique par
    requête)."""
    if not values:
        return None
    parts: list[str] = []
    needs_collection = False
    for v in values:
        if v == "hors_hal":
            parts.append(f"NOT {_SQL_HAS_HAL_SA}")
        elif v == "hors_collection":
            if lab_hal_col is None:
                parts.append(_SQL_HAS_HAL_SA)
            else:
                parts.append(
                    f"({_SQL_HAS_HAL_SA} "
                    "AND NOT EXISTS (SELECT 1 FROM source_publications sd "
                    "WHERE sd.publication_id = p.id AND sd.source = 'hal' "
                    "AND sd.hal_collections @> ARRAY[:flt_hal_collection]))"
                )
                needs_collection = True
        elif v == "notice" and lab_hal_col is not None:
            parts.append(
                f"({_SQL_IN_COLLECTION_SA} "
                f"AND (p.oa_status IS NULL OR p.oa_status::text IN {OA_CLOSED_SQL}))"
            )
            needs_collection = True
        elif v == "ok" and lab_hal_col is not None:
            parts.append(
                f"({_SQL_IN_COLLECTION_SA} "
                f"AND p.oa_status IS NOT NULL AND p.oa_status::text NOT IN {OA_CLOSED_SQL})"
            )
            needs_collection = True
    if not parts:
        return None
    binds: dict[str, Any] = {"flt_hal_collection": lab_hal_col} if needs_collection else {}
    if len(parts) == 1:
        return WhereClause(parts[0], binds)
    return WhereClause("(" + " OR ".join(parts) + ")", binds)


def apc_clause(
    has_apc: list[str], perimeter_structure_ids: list[int], lab_ids: list[int] | None = None
) -> WhereClause | None:
    """Filtre des publications par origine du paiement APC.

    `perimeter_structure_ids` = les structures du périmètre `persons`, que les adapters
    résolvent et qui tiennent lieu de structures « internes » : une publication APC est
    classée "uca" quand au moins un de ses `apc_payments.budget_structure_id` s'y trouve.

    Tous les usages partagent le bind `:flt_apc_root_ids` ; ceux de
    `lab_ids` partagent `:flt_apc_lab_ids`.
    """
    if not has_apc:
        return None
    lab_ids = lab_ids or []
    parts: list[str] = []
    needs_root = False
    needs_lab = False
    for v in has_apc:
        if v == "uca":
            parts.append(
                "EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id "
                "AND ap.budget_structure_id = ANY(CAST(:flt_apc_root_ids AS int[])))"
            )
            needs_root = True
        elif v in ("other", "non_uca"):
            parts.append(
                "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) "
                "AND NOT EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id "
                "AND ap.budget_structure_id = ANY(CAST(:flt_apc_root_ids AS int[]))))"
            )
            needs_root = True
        elif v == "none":
            parts.append(
                "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)"
            )
        elif v == "this_lab" and lab_ids:
            parts.append(
                "EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id "
                "AND ap.lab_structure_id = ANY(CAST(:flt_apc_lab_ids AS int[])))"
            )
            needs_lab = True
        elif v == "other_uca" and lab_ids:
            parts.append(
                "(EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id "
                "AND ap.budget_structure_id = ANY(CAST(:flt_apc_root_ids AS int[]))) "
                "AND NOT EXISTS (SELECT 1 FROM apc_payments ap "
                "WHERE ap.publication_id = p.id "
                "AND ap.lab_structure_id = ANY(CAST(:flt_apc_lab_ids AS int[]))))"
            )
            needs_root = True
            needs_lab = True
    if not parts:
        return None
    binds: dict[str, Any] = {}
    if needs_root:
        binds["flt_apc_root_ids"] = perimeter_structure_ids
    if needs_lab:
        binds["flt_apc_lab_ids"] = lab_ids
    if len(parts) == 1:
        return WhereClause(parts[0], binds)
    return WhereClause("(" + " OR ".join(parts) + ")", binds)


def in_perimeter_person_clause(
    in_perimeter: list[str], person_id: int | None
) -> WhereClause | None:
    if not in_perimeter or not person_id:
        return None
    return _person_toggle_clause(
        in_perimeter,
        """EXISTS (SELECT 1 FROM authorships a
                WHERE a.publication_id = p.id AND a.person_id = :flt_in_per_person
                  AND a.in_perimeter = TRUE)""",
        {"flt_in_per_person": person_id},
    )


def no_lab_clause() -> WhereClause:
    return WhereClause(
        """NOT EXISTS (
            SELECT 1 FROM authorships a
            JOIN authorship_structures aus ON aus.authorship_id = a.id
            JOIN structures s ON s.id = aus.structure_id
            WHERE a.publication_id = p.id
              AND s.structure_type = 'labo'
        )""",
        {},
    )


def country_clause(country_values: list[str]) -> WhereClause | None:
    if not country_values:
        return None
    return WhereClause(
        "p.countries && CAST(:flt_countries AS text[])", {"flt_countries": country_values}
    )


def subject_clause(subject_id: int | None) -> WhereClause | None:
    if not subject_id:
        return None
    return WhereClause(
        "EXISTS (SELECT 1 FROM publication_subjects ps "
        "WHERE ps.publication_id = p.id AND ps.subject_id = :flt_subject_id)",
        {"flt_subject_id": subject_id},
    )


def publisher_id_clause(publisher_id: int | None) -> WhereClause | None:
    if not publisher_id:
        return None
    return WhereClause(
        """EXISTS (
            SELECT 1 FROM journals j2
            WHERE j2.id = p.journal_id AND j2.publisher_id = :flt_publisher_id
        )""",
        {"flt_publisher_id": publisher_id},
    )


def journal_id_clause(journal_id: int | None) -> WhereClause | None:
    if not journal_id:
        return None
    return WhereClause("p.journal_id = :flt_journal_id", {"flt_journal_id": journal_id})


def person_has_identifier_clause(id_type: str, value: bool | None) -> WhereClause | None:
    """Variante SA de `apply_person_has_identifier_filter`.

    `id_type` est une constante d'appel (orcid/idhal/idref) — interpolée
    en SQL. `value` commande la présence ou l'absence d'un EXISTS, donc pas de bind.
    """
    if value is None:
        return None
    negate = "" if value else "NOT "
    return WhereClause(
        f"""{negate}EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id
              AND pi.id_type = '{id_type}'
              AND pi.status != 'rejected'
        )""",
        {},
    )


def person_has_pending_name_forms_clause(value: bool | None) -> WhereClause | None:
    """Personnes ayant ≥1 forme de nom au statut `pending` (à confirmer).

    Les formes dérivées du nom canonique (source `'persons'`) sont confirmées d'office :
    `status = 'pending'` ne capte donc que les formes bibliographiques non encore tranchées."""
    if value is None:
        return None
    negate = "" if value else "NOT "
    return WhereClause(
        f"""{negate}EXISTS (
            SELECT 1 FROM person_name_forms pnf
            WHERE pnf.person_id = p.id AND pnf.status = 'pending'
        )""",
        {},
    )


def person_has_pending_identifiers_clause(value: bool | None) -> WhereClause | None:
    """Personnes ayant ≥1 identifiant **public** au statut `pending` (à confirmer).

    Restreint aux types exposés en UI (`PUBLIC_PERSON_IDENTIFIER_TYPES`) : un
    `hal_person_id` en attente est interne et jamais présenté à l'arbitrage, il ne
    doit donc pas faire remonter la personne dans la file « à confirmer »."""
    if value is None:
        return None
    negate = "" if value else "NOT "
    return WhereClause(
        f"""{negate}EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.status = 'pending'
              AND pi.id_type IN {PUBLIC_PERSON_IDENTIFIER_TYPES_SQL}
        )""",
        {},
    )


def person_department_clause(departments: list[str]) -> WhereClause | None:
    """Filtre : la personne est affectée à l'un des départements RH donnés (alias `prh`)."""
    if not departments:
        return None
    return WhereClause(
        "prh.department_name = ANY(:flt_departments)", {"flt_departments": departments}
    )


def person_role_clause(roles: list[str]) -> WhereClause | None:
    """Filtre : la personne porte l'un des intitulés de poste donnés (alias `prh`)."""
    if not roles:
        return None
    return WhereClause("prh.role_title = ANY(:flt_roles)", {"flt_roles": roles})


def person_has_rh_clause(value: bool | None) -> WhereClause | None:
    """Filtre : la personne a (ou n'a pas) une fiche dans la base RH."""
    if value is None:
        return None
    return WhereClause("prh.id IS NOT NULL" if value else "prh.id IS NULL", {})


def person_rejected_clause(value: bool | None) -> WhereClause | None:
    """Filtre : la personne est (ou n'est pas) écartée par la curation."""
    if value is None:
        return None
    return WhereClause("p.rejected = :flt_person_rejected", {"flt_person_rejected": value})


def person_in_lab_clause(lab_id: int | None) -> WhereClause | None:
    """Filtre : la personne (alias `p`) a un authorship rôle author rattaché au labo.

    Sert à scoper l'annuaire/les facettes personnes à un laboratoire — même
    sémantique que le scope publications `lab_clause`, transposée sur `person_id`.
    """
    if not lab_id:
        return None
    return WhereClause(
        """EXISTS (
            SELECT 1 FROM authorships a
            JOIN authorship_structures aus ON aus.authorship_id = a.id
            WHERE a.person_id = p.id
              AND aus.structure_id = :flt_person_lab_id
              AND a.roles && ARRAY['author']::text[]
        )""",
        {"flt_person_lab_id": lab_id},
    )


_PERSONS_SORT_MAP = {
    "name_asc": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
    "name_desc": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
    "signatures_asc": "signature_count ASC, LOWER(p.last_name) ASC",
    "signatures_desc": "signature_count DESC, LOWER(p.last_name) ASC",
    "signatures_as_author_asc": "signature_count_as_author ASC, LOWER(p.last_name) ASC",
    "signatures_as_author_desc": "signature_count_as_author DESC, LOWER(p.last_name) ASC",
    "in_perimeter_signatures_asc": "in_perimeter_signature_count ASC, LOWER(p.last_name) ASC",
    "in_perimeter_signatures_desc": "in_perimeter_signature_count DESC, LOWER(p.last_name) ASC",
    "dept_asc": "prh.department_name ASC NULLS LAST, LOWER(p.last_name) ASC",
    "dept_desc": "prh.department_name DESC NULLS LAST, LOWER(p.last_name) ASC",
    "role_asc": "prh.role_title ASC NULLS LAST, LOWER(p.last_name) ASC",
    "role_desc": "prh.role_title DESC NULLS LAST, LOWER(p.last_name) ASC",
}


def persons_sort_clause(sort: str) -> str:
    """Clause ORDER BY de la liste des personnes. Le nom est celui du contrat, validé en amont."""
    return _PERSONS_SORT_MAP[sort]
