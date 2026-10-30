"""Fragments SQL et constructeurs de filtres pour les requêtes de lecture.

Chaque `*_clause(...)` renvoie un `WhereClause | None`, à assembler par `assemble_where(...)`. Les fragments emploient les paramètres nommés `:nom` de SQLAlchemy.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from domain.normalize import normalize_text
from domain.persons.identifiers import AttributionStatus
from domain.persons.person import PersonExclusion
from domain.publications.metadata import (
    ACCESS_LEVELS,
    OA_CLOSED_STATUSES,
    OA_OPEN_STATUSES,
    OaStatus,
)
from domain.sources.registry import PROFILES, SOURCE_FILTER_PREFIXES, Source
from domain.structures.structure import StructureType
from infrastructure.read_models.publications.models import (
    DOI_AGENCY_SOURCES,
    NO_DOI,
    NO_LICENSE,
    OTHER_DOI_AGENCY,
)
from infrastructure.sql_fragments import has_author_role, pending_name_form


def _sql_list(values: Iterable[str]) -> str:
    """Liste SQL littérale `('a','b',…)` de constantes du domaine, interpolée telle quelle : jamais de valeur saisie."""
    return "(" + ",".join(f"'{v}'" for v in sorted(values)) + ")"


OA_OPEN_SQL = _sql_list(OA_OPEN_STATUSES)
OA_CLOSED_SQL = _sql_list(OA_CLOSED_STATUSES)

# Colonnes de ventilation open access par statut (alias `p` des publications), partagées par les statistiques des éditeurs, revues, laboratoires et années : une colonne par statut de `OaStatus`, nommée par sa valeur, dans l'ordre de l'enum.
OA_BREAKDOWN_COLS_SQL = ",\n            ".join(
    f"COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = '{status.value}') AS {status.value}"
    for status in OaStatus
)


def publication_in_perimeter(alias: str = "p") -> str:
    """Filtre SQL : la publication aliasée `alias` est dans le périmètre (`in_perimeter`, colonne générée vraie quand la publication a des indices de l'entrée dans le périmètre).

    Seules les listes du périmètre l'appliquent ; les vues par personne montrent tout. `alias` sert quand `p` est déjà pris.
    """
    return f"({alias}.in_perimeter)"


# La plupart des requêtes aliasent les publications `p` : constante de commodité.
PUBLICATION_IS_IN_PERIMETER = publication_in_perimeter()

# Un sujet dont l'usage global dépasse ce seuil est trop générique pour un nuage de mots : « research article » ou « science » arrivent en tête partout, et masquent ce qui distingue le contexte affiché.
GENERIC_SUBJECT_MAX_USAGE = 5000

# Filtre SQL : le sujet (alias `s`) est hors des sujets génériques. Les quatre nuages de mots (éditeur, revue, laboratoire, personne) écartent le même ensemble.
SUBJECT_IS_NOT_GENERIC = f"(s.usage_count <= {GENERIC_SUBJECT_MAX_USAGE})"


def entity_subjects_sql(entity_predicate: str) -> str:
    """SQL des sujets les plus fréquents des publications retenues par `entity_predicate` (sur l'alias `p`), au grain de `publication_subjects`. Chaque page d'entité (revue, éditeur, laboratoire, personne) passe son propre prédicat ; `:lim` plafonne le nombre de sujets."""
    return f"""
        SELECT s.id, s.label, COUNT(DISTINCT p.id) AS n
        FROM publication_subjects ps
        JOIN publications p ON p.id = ps.publication_id
        JOIN subjects s ON s.id = ps.subject_id
        WHERE {entity_predicate}
          AND {SUBJECT_IS_NOT_GENERIC}
        GROUP BY s.id, s.label
        ORDER BY n DESC, lower(s.label)
        LIMIT :lim
    """


@dataclass(frozen=True)
class WhereClause:
    """Fragment SQL et ses paramètres nommés (`:nom`), à assembler par `assemble_where(...)` puis exécuter sur une `Connection` SQLAlchemy. Incompatible avec un curseur psycopg."""

    sql: str
    binds: dict[str, object]


def assemble_where(clauses: list[WhereClause | None]) -> tuple[str, dict[str, object]]:
    """Condition SQL et paramètres des fragments assemblés. Sans clause, renvoie `("TRUE", {})` : l'appelant écrit `f"WHERE {where_sql}"` sans cas particulier."""
    valid = [c for c in clauses if c is not None]
    if not valid:
        return "TRUE", {}
    sql = " AND ".join(c.sql for c in valid)
    binds: dict[str, object] = {}
    for c in valid:
        binds.update(c.binds)
    return sql, binds


def year_clause(years: list[int]) -> WhereClause | None:
    if not years:
        return None
    return WhereClause("p.publication_year = ANY(:flt_years)", {"flt_years": years})


def lab_clause(lab_ids: list[int]) -> WhereClause | None:
    if not lab_ids:
        return None
    return WhereClause(
        """EXISTS (
            SELECT 1 FROM publication_structures ps
            WHERE ps.publication_id = p.id
              AND ps.structure_id = ANY(:flt_lab_ids)
        )""",
        {"flt_lab_ids": lab_ids},
    )


# ROR propres aux structures `:own_structure_ids` : ceux des structures et de leurs tutelles (`structure_parents`), avec leurs ancêtres ROR. Les organisations partenaires les excluent.
OWN_RORS_SQL = """
    WITH RECURSIVE own_structures AS (
        SELECT unnest(CAST(:own_structure_ids AS integer[])) AS id
        UNION
        SELECT sp.parent_id FROM structure_parents sp JOIN own_structures o ON sp.child_id = o.id
    ),
    own_rors AS (
        SELECT s.ror_id FROM structures s JOIN own_structures o ON o.id = s.id
        WHERE s.ror_id IS NOT NULL
        UNION
        SELECT rr.parent_ror_id FROM ror_relations rr JOIN own_rors r ON rr.child_ror_id = r.ror_id
    )
    SELECT ror_id FROM own_rors
"""


def own_structure_ids(lab_ids: list[int], perimeter_structure_ids: list[int]) -> list[int]:
    """Structures dont les ROR sont exclus des organisations partenaires : les laboratoires sélectionnés, sinon tout le périmètre."""
    return lab_ids or perimeter_structure_ids


def partner_clause(ror_ids: list[str]) -> WhereClause | None:
    """Filtre par organisation partenaire : un ROR des auteurs de la publication, ancêtres compris (`publication_rors`). Les valeurs se combinent en OR."""
    if not ror_ids:
        return None
    return WhereClause(
        """EXISTS (
            SELECT 1 FROM publication_rors pr
            WHERE pr.publication_id = p.id AND pr.ror_id = ANY(:flt_partner_rors)
        )""",
        {"flt_partner_rors": ror_ids},
    )


def license_clause(values: list[str]) -> WhereClause | None:
    """Filtre par licence de la version éditeur. `NO_LICENSE` retient les publications sans licence connue ; les valeurs se combinent en OR."""
    if not values:
        return None
    named = [v for v in values if v != NO_LICENSE]
    parts = ["p.license::text = ANY(:flt_license)"] if named else []
    if NO_LICENSE in values:
        parts.append("p.license IS NULL")
    sql = parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    return WhereClause(sql, {"flt_license": named} if named else {})


# Agence d'enregistrement du DOI de la publication `p`, au vocabulaire `DOI_AGENCY_FILTER_VALUES`, lue dans `doi_prefixes.ra` par le préfixe du DOI. Le filtre et la facette lisent cette expression, donc classent de la même façon.
_DOI_AGENCY_CASES = " ".join(
    f"WHEN '{PROFILES[source].registration_agency}' THEN '{source.value}'"
    for source in DOI_AGENCY_SOURCES
)
DOI_AGENCY_SQL = f"""(CASE
    WHEN p.doi IS NULL THEN '{NO_DOI}'
    ELSE COALESCE(
        (SELECT CASE dp.ra {_DOI_AGENCY_CASES} END
         FROM doi_prefixes dp WHERE dp.prefix = p.doi_prefix),
        '{OTHER_DOI_AGENCY}'
    )
END)"""


def doi_agency_clause(values: list[str]) -> WhereClause | None:
    """Filtre par agence d'enregistrement du DOI (`DOI_AGENCY_SQL`), les valeurs combinées en OR."""
    if not values:
        return None
    return WhereClause(
        f"{DOI_AGENCY_SQL} = ANY(CAST(:flt_doi_agency AS text[]))", {"flt_doi_agency": values}
    )


def oa_clause(oa_status: list[str]) -> WhereClause | None:
    if not oa_status:
        return None
    if len(oa_status) == 1:
        return WhereClause("p.oa_status::text = :flt_oa_status", {"flt_oa_status": oa_status[0]})
    return WhereClause("p.oa_status::text = ANY(:flt_oa_status)", {"flt_oa_status": oa_status})


def access_clause(access: list[str]) -> WhereClause | None:
    """Filtre par niveau d'accès, les niveaux demandés combinés en OR.

    Les niveaux ventilent les statuts OA (`ACCESS_LEVELS`) : filtrer sur un niveau revient à filtrer sur les statuts qu'il recouvre. Un `oa_status` nul compte comme fermé.
    """
    if not access:
        return None
    statuses = {s for level in access for s in ACCESS_LEVELS.get(level, frozenset())}
    include_null = "closed" in access
    if not statuses and not include_null:
        return None
    conditions: list[str] = []
    binds: dict[str, object] = {}
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
    """Recherche plein texte : titre normalisé ou libellé de sujet. La liste, l'export et les facettes la partagent : les trois comptent le même ensemble. Paramètre `:flt_search_pat`."""
    if not search:
        return None
    pattern = f"%{normalize_text(search)}%"
    return WhereClause(
        "(p.title_normalized ILIKE :flt_search_pat "
        "OR p.id IN (SELECT ps.publication_id FROM publication_subjects ps "
        "JOIN subjects s ON s.id = ps.subject_id "
        "WHERE s.label_normalized ILIKE :flt_search_pat))",
        {"flt_search_pat": pattern},
    )


def person_search_clause(search: str) -> WhereClause | None:
    """Recherche par nom : chaque mot saisi figure dans le nom ou le prénom (accent-insensible).

    L'ordre des mots est indifférent : « Valérie Legué » et « Legué Valérie » trouvent la même personne. Partagée par l'annuaire des personnes, ses facettes et l'autocomplétion. Alias `p` : la personne. Paramètres `:flt_person_search_<rang du mot>`.
    """
    words = search.split()
    if not words:
        return None
    conditions: list[str] = []
    binds: dict[str, object] = {}
    for i, word in enumerate(words):
        key = f"flt_person_search_{i}"
        conditions.append(
            f"(unaccent(p.last_name) ILIKE unaccent(:{key}) "
            f"OR unaccent(p.first_name) ILIKE unaccent(:{key}))"
        )
        binds[key] = f"%{word}%"
    return WhereClause(" AND ".join(conditions), binds)


def source_clause(source_values: list[str]) -> WhereClause | None:
    """Filtre par source, sur `publications.sources`. Les valeurs sont des `{prefix}_{yes|no}`, constantes de l'interface, interpolées sans paramètre."""
    parts: list[str] = []
    for sv in source_values:
        bits = sv.rsplit("_", 1)
        if len(bits) != 2:
            continue
        prefix, mode = bits
        source = SOURCE_FILTER_PREFIXES.get(prefix)
        if not source or mode not in ("yes", "no"):
            continue
        if mode == "yes":
            parts.append(f"p.sources @> ARRAY['{source.value}'::source_type]")
        else:
            parts.append(f"NOT p.sources @> ARRAY['{source.value}'::source_type]")
    if not parts:
        return None
    return WhereClause(" AND ".join(parts), {})


def _authored_by(person_id: int, bind: str) -> WhereClause:
    """La personne est auteur (rôle 'author') de la publication ; son id est lié sous `:bind`."""
    return WhereClause(
        f"""EXISTS (SELECT 1 FROM contributions a
                WHERE a.publication_id = p.id AND a.person_id = :{bind}
                  AND {has_author_role("a")})""",
        {bind: person_id},
    )


def person_clause(person_id: int) -> WhereClause:
    """Filtre : la personne donnée est auteur (rôle 'author') de la publication."""
    return _authored_by(person_id, "flt_person_id")


def author_clause(author_id: int | None) -> WhereClause | None:
    """Filtre : la personne choisie en facette est auteur de la publication.

    Se combine à `person_clause` sur une page personne (publications cosignées), d'où un paramètre lié distinct.
    """
    if not author_id:
        return None
    return _authored_by(author_id, "flt_author_id")


def _toggle_clause(
    values: list[str], exists_sql: str, binds: dict[str, object]
) -> WhereClause | None:
    """Facette binaire `yes`/`no` sur un prédicat EXISTS. `yes` retient les publications qui vérifient `exists_sql`, `no` les autres, combinés en OR : cocher les deux laisse tout passer. Une valeur inconnue est ignorée."""
    parts: list[str] = []
    if "yes" in values:
        parts.append(exists_sql)
    if "no" in values:
        parts.append(f"NOT {exists_sql}")
    if not parts:
        return None
    sql = parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    return WhereClause(sql, binds)


def corresponding_clause(person_id: int | None, corr_filter: list[str]) -> WhereClause | None:
    if not corr_filter or not person_id:
        return None
    return _toggle_clause(
        corr_filter,
        """EXISTS (SELECT 1 FROM contributions a
                WHERE a.publication_id = p.id AND a.person_id = :flt_corr_person
                  AND a.is_corresponding = TRUE)""",
        {"flt_corr_person": person_id},
    )


_SQL_HAS_HAL_SOURCE_CONTRIBUTION = (
    "EXISTS (SELECT 1 FROM source_records sr "
    f"WHERE sr.publication_id = p.id AND sr.source = '{Source.HAL.value}')"
)
_SQL_IN_COLLECTION_SOURCE_CONTRIBUTION = (
    "EXISTS (SELECT 1 FROM source_records sr "
    f"WHERE sr.publication_id = p.id AND sr.source = '{Source.HAL.value}' "
    "AND sr.hal_collections @> ARRAY[:flt_hal_collection])"
)


def hal_status_expression(lab_hal_col: str | None) -> WhereClause:
    """Statut de dépôt HAL de la publication `p` (`HAL_DEPOSIT_STATUSES`), au regard de la collection du laboratoire.

    Sans collection déclarée, aucune publication n'est en collection : un dépôt HAL vaut `hors_collection`. Le filtre, la facette et l'export lisent tous cette expression, donc classent de la même façon.
    """
    if lab_hal_col is None:
        return WhereClause(
            f"(CASE WHEN {_SQL_HAS_HAL_SOURCE_CONTRIBUTION} THEN 'hors_collection' ELSE 'hors_hal' END)",
            {},
        )
    return WhereClause(
        f"""(CASE
            WHEN NOT {_SQL_HAS_HAL_SOURCE_CONTRIBUTION} THEN 'hors_hal'
            WHEN NOT {_SQL_IN_COLLECTION_SOURCE_CONTRIBUTION} THEN 'hors_collection'
            WHEN p.oa_status IS NULL OR p.oa_status::text IN {OA_CLOSED_SQL} THEN 'notice'
            ELSE 'ok'
        END)""",
        {"flt_hal_collection": lab_hal_col},
    )


def hal_status_clause(values: list[str], lab_hal_col: str | None) -> WhereClause | None:
    """Filtre : le statut de dépôt HAL de la publication est l'un de `values`."""
    if not values:
        return None
    status = hal_status_expression(lab_hal_col)
    return WhereClause(
        f"{status.sql} = ANY(CAST(:flt_hal_status AS text[]))",
        {**status.binds, "flt_hal_status": values},
    )


def institution_apc_payment_sql(root_ids_param: str) -> str:
    """Condition SQL vraie quand la publication `p` a un paiement d'APC imputé au budget d'une structure du périmètre. Le paramètre nommé `root_ids_param` contient les identifiants de ces structures."""
    return (
        "EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id "
        f"AND ap.budget_structure_id = ANY(CAST(:{root_ids_param} AS int[])))"
    )


def apc_clause(has_apc: list[str], perimeter_structure_ids: list[int]) -> WhereClause | None:
    """Filtre `yes` / `no` des publications dont un paiement d'APC est imputé au budget d'une structure du périmètre `persons` (`perimeter_structure_ids`, que les adaptateurs résolvent)."""
    return _toggle_clause(
        has_apc,
        institution_apc_payment_sql("flt_apc_root_ids"),
        {"flt_apc_root_ids": perimeter_structure_ids},
    )


def in_perimeter_person_clause(
    in_perimeter: list[str], person_id: int | None
) -> WhereClause | None:
    if not in_perimeter or not person_id:
        return None
    return _toggle_clause(
        in_perimeter,
        """EXISTS (SELECT 1 FROM contributions a
                WHERE a.publication_id = p.id AND a.person_id = :flt_in_per_person
                  AND a.in_perimeter = TRUE)""",
        {"flt_in_per_person": person_id},
    )


def no_lab_clause() -> WhereClause:
    return WhereClause(
        f"""NOT EXISTS (
            SELECT 1 FROM publication_structures ps
            JOIN structures s ON s.id = ps.structure_id
            WHERE ps.publication_id = p.id
              AND s.structure_type = '{StructureType.LABO.value}'
        )""",
        {},
    )


def country_clause(country_values: list[str]) -> WhereClause | None:
    if not country_values:
        return None
    return WhereClause(
        "p.countries && CAST(:flt_countries AS text[])", {"flt_countries": country_values}
    )


def language_clause(language_codes: list[str]) -> WhereClause | None:
    """Filtre : la langue de la publication est l'une des langues choisies."""
    if not language_codes:
        return None
    return WhereClause(
        "p.language = ANY(CAST(:flt_languages AS text[]))", {"flt_languages": language_codes}
    )


def subject_clause(subject_ids: list[int]) -> WhereClause | None:
    """Filtre : la publication a au moins un des sujets."""
    if not subject_ids:
        return None
    return WhereClause(
        "EXISTS (SELECT 1 FROM publication_subjects ps "
        "WHERE ps.publication_id = p.id AND ps.subject_id = ANY(CAST(:flt_subject_ids AS int[])))",
        {"flt_subject_ids": subject_ids},
    )


def publisher_id_clause(publisher_id: int | None) -> WhereClause | None:
    if not publisher_id:
        return None
    return WhereClause("p.publisher_id = :flt_publisher_id", {"flt_publisher_id": publisher_id})


def serial_id_clause(serial_id: int | None) -> WhereClause | None:
    if not serial_id:
        return None
    return WhereClause("p.serial_id = :flt_serial_id", {"flt_serial_id": serial_id})


def monograph_id_clause(monograph_id: int | None) -> WhereClause | None:
    if not monograph_id:
        return None
    return WhereClause("p.monograph_id = :flt_monograph_id", {"flt_monograph_id": monograph_id})


def person_has_identifier_sql(id_type: str) -> str:
    """Prédicat : la personne `p` a un identifiant de ce type, non rejeté. Le type est une constante d'appel (orcid, idhal, idref), interpolée en SQL."""
    return f"""EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id
              AND pi.id_type = '{id_type}'
              AND pi.status != '{AttributionStatus.REJECTED.value}'
        )"""


def person_has_identifier_clause(id_type: str, value: bool | None) -> WhereClause | None:
    """Filtre : la personne a (`value` vrai) ou non un identifiant de ce type (`person_has_identifier_sql`)."""
    if value is None:
        return None
    negate = "" if value else "NOT "
    return WhereClause(f"{negate}{person_has_identifier_sql(id_type)}", {})


# Prédicat : la personne `p` a au moins une forme de nom à confirmer (`pending_name_form`).
PERSON_HAS_PENDING_NAME_FORMS_SQL = f"""EXISTS (
            SELECT 1 FROM person_name_forms pnf
            WHERE pnf.person_id = p.id AND {pending_name_form("pnf")}
        )"""

# Prédicat : la personne `p` a au moins un identifiant à confirmer (`pending`).
PERSON_HAS_PENDING_IDENTIFIERS_SQL = f"""EXISTS (
            SELECT 1 FROM person_identifiers pi
            WHERE pi.person_id = p.id AND pi.status = '{AttributionStatus.PENDING.value}'
        )"""


def person_has_pending_name_forms_clause(value: bool | None) -> WhereClause | None:
    """Filtre : la personne a (`value` vrai) ou non une forme de nom à confirmer (`PERSON_HAS_PENDING_NAME_FORMS_SQL`)."""
    if value is None:
        return None
    negate = "" if value else "NOT "
    return WhereClause(f"{negate}{PERSON_HAS_PENDING_NAME_FORMS_SQL}", {})


def person_has_pending_identifiers_clause(value: bool | None) -> WhereClause | None:
    """Filtre : la personne a (`value` vrai) ou non un identifiant à confirmer (`PERSON_HAS_PENDING_IDENTIFIERS_SQL`)."""
    if value is None:
        return None
    negate = "" if value else "NOT "
    return WhereClause(f"{negate}{PERSON_HAS_PENDING_IDENTIFIERS_SQL}", {})


def person_department_clause(departments: list[str]) -> WhereClause | None:
    """Filtre : la personne est affectée à l'un des départements RH donnés (alias `prh`)."""
    if not departments:
        return None
    return WhereClause(
        "prh.department_name = ANY(:flt_departments)", {"flt_departments": departments}
    )


def person_role_clause(roles: list[str]) -> WhereClause | None:
    """Filtre : la personne a l'un des intitulés de poste donnés (alias `prh`)."""
    if not roles:
        return None
    return WhereClause("prh.role_title = ANY(:flt_roles)", {"flt_roles": roles})


def person_has_rh_clause(value: bool | None) -> WhereClause | None:
    """Filtre : la personne a (ou n'a pas) une fiche dans la base RH."""
    if value is None:
        return None
    return WhereClause("prh.id IS NOT NULL" if value else "prh.id IS NULL", {})


def person_active_clause(value: bool | None) -> WhereClause | None:
    """Filtre : la personne a (ou n'a pas) une contribution ou une fiche RH."""
    if value is None:
        return None
    active = (
        "(prh.id IS NOT NULL OR EXISTS (SELECT 1 FROM contributions a WHERE a.person_id = p.id))"
    )
    return WhereClause(active if value else f"NOT {active}", {})


def person_exclusion_clause(exclusions: list[PersonExclusion | None]) -> WhereClause | None:
    """Filtre : le motif d'exclusion de la personne figure dans `exclusions`, `None` désignant une personne retenue."""
    if not exclusions:
        return None
    reasons = [e.value for e in exclusions if e is not None]
    parts = ["p.exclusion = ANY(CAST(:flt_person_exclusions AS person_exclusion[]))"]
    if None in exclusions:
        parts.append("p.exclusion IS NULL")
    return WhereClause(f"({' OR '.join(parts)})", {"flt_person_exclusions": reasons})


def person_in_lab_clause(lab_id: int | None) -> WhereClause | None:
    """Filtre : la personne (alias `p`) a une contribution d'auteur rattachée au laboratoire. Restreint l'annuaire et ses facettes à un laboratoire, comme `lab_clause` pour les publications."""
    if not lab_id:
        return None
    return WhereClause(
        f"""EXISTS (
            SELECT 1 FROM contributions a
            JOIN contribution_structures aus ON aus.contribution_id = a.id
            WHERE a.person_id = p.id
              AND aus.structure_id = :flt_person_lab_id
              AND {has_author_role("a")}
        )""",
        {"flt_person_lab_id": lab_id},
    )


_PERSONS_SORT_MAP = {
    "name_asc": "LOWER(p.last_name) ASC, LOWER(p.first_name) ASC",
    "name_desc": "LOWER(p.last_name) DESC, LOWER(p.first_name) DESC",
    "contributions_asc": "contribution_count ASC, LOWER(p.last_name) ASC",
    "contributions_desc": "contribution_count DESC, LOWER(p.last_name) ASC",
    "in_perimeter_contributions_asc": "in_perimeter_contribution_count ASC, LOWER(p.last_name) ASC",
    "in_perimeter_contributions_desc": "in_perimeter_contribution_count DESC, LOWER(p.last_name) ASC",
    "dept_asc": "prh.department_name ASC NULLS LAST, LOWER(p.last_name) ASC",
    "dept_desc": "prh.department_name DESC NULLS LAST, LOWER(p.last_name) ASC",
    "role_asc": "prh.role_title ASC NULLS LAST, LOWER(p.last_name) ASC",
    "role_desc": "prh.role_title DESC NULLS LAST, LOWER(p.last_name) ASC",
}


def persons_sort_clause(sort: str) -> str:
    """Clause ORDER BY de la liste des personnes. Le nom est celui du contrat, validé en amont."""
    return _PERSONS_SORT_MAP[sort]
