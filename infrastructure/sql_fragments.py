"""Fragments SQL partagés entre plusieurs adaptateurs de l'API ou du pipeline.

Trois formes : des fragments rendus depuis des constantes du domaine (`in_clause`, `case_priority` — valeurs d'enums ou ordres de priorité, jamais d'entrée utilisateur : interpolation directe sûre), des expressions rendues depuis les alias de la requête hôte (identifiants d'une signature), et des expressions SQL figées.
"""

from application.ports.repositories.address_repository import AddressCountryFilter
from domain.journals.journal import OaModel
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.persons.matching import ORCID_MATCH_SOURCES, STRONG_PERSON_IDENTIFIER_TYPES
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE
from domain.publications.contribution_roles import ContributionRole
from domain.source_records.raw_metadata import CORRECTED_BY, RAW
from domain.sources.person_search import SEARCHED_IDENTIFIER_STATUSES
from domain.sources.registry import SOURCE_PRIORITY
from domain.structures.perimeter_evidence import PerimeterEvidence


def in_clause(values: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"


def person_source_contribution(source_contribution: str = "sa") -> str:
    """Condition vraie quand la signature aliasée `signature` désigne une personne : elle n'est ni collective, ni un doublon d'auteur (`duplicate_of`)."""
    return f"NOT {source_contribution}.collective AND {source_contribution}.duplicate_of IS NULL"


def pinned(source_contribution_id: str) -> str:
    """Condition vraie quand l'administration a épinglé la signature d'identifiant `source_contribution_id` à une personne (`confirmed_source_contributions`)."""
    return f"EXISTS (SELECT 1 FROM confirmed_source_contributions ca WHERE ca.source_contribution_id = {source_contribution_id})"


def active_name_form(form: str) -> str:
    """Condition vraie quand la forme de nom `form` (ligne de `person_name_forms`, ou son alias) désigne sa personne au matching : une forme dérivée du nom de la personne, ou une forme non rejetée."""
    return (
        f"({form}.status <> '{AttributionStatus.REJECTED.value}'"
        f" OR '{CANONICAL_NAME_FORM_SOURCE}' = ANY({form}.sources))"
    )


DETACHED_SOURCE_CONTRIBUTION = "person_id = NULL, resolution_mode = NULL"
"""Affectations d'un `UPDATE source_contributions` qui détache une signature de sa personne."""


def diamond_journal_sql(journal: str = "j") -> str:
    """Condition vraie quand la revue aliasée `journal` est diamant : marquée `diamond`, ou présente dans le DOAJ sans APC ni autres frais. NULL quand la revue est absente d'une jointure externe."""
    return (
        f"({journal}.oa_model = '{OaModel.DIAMOND.value}' OR ({journal}.is_in_doaj"
        f" AND {journal}.doaj_payload->>'APC' = 'No'"
        f" AND {journal}.doaj_payload->>'Has other fees' = 'No'))"
    )


def has_author_role(source_contribution: str = "sa") -> str:
    """Condition vraie quand la signature ou la contribution aliasée `signature` tient le rôle d'auteur."""
    return f"{source_contribution}.roles && ARRAY['{ContributionRole.AUTHOR.value}']::text[]"


def identifier_neutralized(
    id_type: str, source_contribution: str = "sa", *, reason: str | None = None
) -> str:
    """Condition vraie quand la signature aliasée `signature` neutralise l'identifiant `id_type`, pour le motif `reason` s'il est donné.

    `id_type` est une expression SQL : littéral (`'orcid'`), paramètre (`:id_type`) ou colonne.
    """
    if reason is None:
        return f"coalesce({source_contribution}.neutralized_identifiers ? {id_type}, false)"
    return (
        f"coalesce({source_contribution}.neutralized_identifiers ->> {id_type} = '{reason}', false)"
    )


def usable_identifier(
    id_type: str, *, source_contribution: str = "sa", contributor_information: str = "aik"
) -> str:
    """Valeur de l'identifiant `id_type` dans l'identité d'une signature, NULL quand la signature le neutralise."""
    return (
        f"CASE WHEN {identifier_neutralized(id_type, source_contribution)} THEN NULL"
        f" ELSE {contributor_information}.identifiers ->> {id_type} END"
    )


def trusted_identifier_sql(id_type: str, source_contribution: str = "sa") -> str:
    """Condition SQL de `trusted_identifier` pour l'identifiant `id_type` de la signature aliasée `signature`."""
    if id_type != PersonIdentifierType.ORCID:
        return "TRUE"
    return f"{source_contribution}.source::text IN {in_clause(tuple(sorted(ORCID_MATCH_SOURCES)))}"


def strong_identifier_source_contributions(
    id_type: PersonIdentifierType,
    *,
    identifiers: str,
    select: str,
    joins: str = "",
    where: str = "",
) -> str:
    """Requête des signatures `sa_auth` dont l'identité contient l'identifiant `id_type` d'une ligne de `identifiers`.

    `identifiers` : table ou sous-requête, aliasée `pi`, de colonnes `person_id`, `id_type`, `id_value`. L'identifiant que la signature neutralise est écarté, et celui que sa source rend non fiable (`trusted_identifier_sql`). La requête rejoint les signatures par `contributor_information_id` après un rapprochement sur `contributor_information`.
    """
    return f"""
        SELECT {select}
        FROM {identifiers} pi
        JOIN contributor_information aik ON aik.identifiers->>'{id_type}' = pi.id_value
        JOIN source_contributions sa_auth ON sa_auth.contributor_information_id = aik.id
        {joins}
        WHERE pi.id_type = '{id_type}'
          AND aik.identifiers ? '{id_type}'
          AND NOT {identifier_neutralized(f"'{id_type}'", "sa_auth")}
          AND {trusted_identifier_sql(id_type, "sa_auth")}
          {f"AND {where}" if where else ""}
    """


# Identifiants des personnes RH, aux statuts qui les font interroger, avec les années de présence : de l'année qui suit l'arrivée à l'année de fin de contrat. Sans date : 0, 9999.
_RH_IDENTIFIERS = f"""(
    SELECT pi.person_id, pi.id_type::text AS id_type, pi.id_value,
           coalesce(extract(year FROM r.start_date)::int + 1, 0) AS first_year,
           coalesce(extract(year FROM r.end_date)::int, 9999) AS last_year
    FROM person_identifiers pi
    JOIN hr_records r ON r.person_id = pi.person_id
    WHERE pi.status::text IN {in_clause(tuple(sorted(SEARCHED_IDENTIFIER_STATUSES)))}
)"""


def hr_record_source_contributions(source_contribution_filter: str = "") -> str:
    """Requête des ids des signatures qui entrent dans le périmètre par l'identité : identifiant fort d'une personne RH, document paru entre l'année qui suit son arrivée et l'année de fin de son contrat, sans rejet de la personne pour la notice.

    `source_contribution_filter` : condition supplémentaire sur la signature `sa_auth`.
    """
    conditions = [
        "sp_rh.publication_year BETWEEN pi.first_year AND pi.last_year",
        (
            "NOT EXISTS (SELECT 1 FROM rejected_contributions rej"
            " WHERE rej.source_record_id = sa_auth.source_record_id"
            " AND rej.person_id = pi.person_id)"
        ),
    ]
    if source_contribution_filter:
        conditions.append(source_contribution_filter)
    return " UNION ".join(
        strong_identifier_source_contributions(
            id_type,
            identifiers=_RH_IDENTIFIERS,
            select="sa_auth.id",
            joins="JOIN source_records sp_rh ON sp_rh.id = sa_auth.source_record_id",
            where=" AND ".join(conditions),
        )
        for id_type in STRONG_PERSON_IDENTIFIER_TYPES
    )


# Paires (publication, personne) rejetées : une publication est rejetée pour une personne dès qu'une de ses notices l'est.
REJECTED_PAIRS = (
    "SELECT sp_rej.publication_id, rej.person_id FROM rejected_contributions rej"
    " JOIN source_records sp_rej ON sp_rej.id = rej.source_record_id"
)


def publication_rejected_for(publication_id: str, person_id: str) -> str:
    """Condition vraie quand la publication `publication_id` est rejetée pour la personne `person_id` (expressions SQL) : une de ses notices l'est."""
    return (
        "EXISTS (SELECT 1 FROM rejected_contributions rej"
        " JOIN source_records sp_rej ON sp_rej.id = rej.source_record_id"
        f" WHERE sp_rej.publication_id = {publication_id} AND rej.person_id = {person_id})"
    )


# Tableau d'indices vide : hors du périmètre.
NO_PERIMETER_EVIDENCE = "'{}'::perimeter_evidence[]"


def source_contribution_perimeter_evidence(source_contribution_ids: str | None = None) -> str:
    """Requête des indices de l'entrée dans le périmètre de chaque signature qui en a : colonnes `id` et `evidence`, tableau trié.

    `:perimeter_ids` : structures du périmètre, atteintes par la matview `source_contribution_structures`. `source_contribution_ids` : nom d'un paramètre lié, tableau d'ids, qui restreint les signatures.
    """
    by_structure = "sas.structure_id = ANY(:perimeter_ids)"
    by_contributor_information = ""
    if source_contribution_ids:
        by_structure += f" AND sas.source_contribution_id = ANY(:{source_contribution_ids})"
        by_contributor_information = f"sa_auth.id = ANY(:{source_contribution_ids})"
    return f"""
        SELECT id, array_agg(evidence ORDER BY evidence) AS evidence
        FROM (
            SELECT sas.source_contribution_id AS id, sas.evidence
            FROM source_contribution_structures sas
            WHERE {by_structure}
            UNION
            SELECT rh.id, '{PerimeterEvidence.HR_RECORD}'::perimeter_evidence
            FROM ({hr_record_source_contributions(by_contributor_information)}) rh
        ) e
        GROUP BY id
    """


def corrected(field: str, source_record: str = "sp") -> str:
    """Condition vraie quand la phase `metadata_correction` a corrigé le champ `field` de la notice aliasée `notice` (`domain.source_records.raw_metadata`)."""
    return f"{source_record}.raw_metadata ? '{field}'"


def corrected_by(field: str, source_record: str = "sp") -> str:
    """Règle qui a corrigé le champ `field` de la notice aliasée `notice`. NULL quand le champ est intact."""
    return f"{source_record}.raw_metadata -> '{field}' ->> '{CORRECTED_BY}'"


def stashed_raw(field: str, source_record: str = "sp") -> str:
    """Valeur que la source donne pour le champ `field` de la notice aliasée `notice`, quand une correction l'a changée. NULL quand le champ est intact."""
    return f"{source_record}.raw_metadata -> '{field}' ->> '{RAW}'"


def raw_column(field: str, source_record: str = "sp") -> str:
    """Valeur que la source donne pour la colonne texte `field` de la notice aliasée `notice` : la valeur conservée par une correction, sinon la colonne (`raw_value`)."""
    return (
        f"CASE WHEN {source_record}.raw_metadata -> '{field}' ? '{RAW}'"
        f" THEN {stashed_raw(field, source_record)} ELSE {source_record}.{field} END"
    )


# Restrictions de `insert_missing_contributions_sql` et `propagate_contribution_attributes_sql`, sur la signature `sa` et sa notice `sp`.
PERSON_PUBLICATIONS_SCOPE = (
    "AND sa.person_id = :person_id AND sp.publication_id = ANY(:publication_ids)"
)
"""Paires (publication, personne) de la personne `:person_id` sur les publications `:publication_ids`."""

SOURCE_CONTRIBUTIONS_SCOPE = """AND (sp.publication_id, sa.person_id) IN (
    SELECT s_sp.publication_id, s.person_id
    FROM source_contributions s JOIN source_records s_sp ON s_sp.id = s.source_record_id
    WHERE s.id = ANY(:source_contribution_ids)
)"""
"""Paires (publication, personne) des signatures `:source_contribution_ids`."""


def insert_missing_contributions_sql(*, scope: str = "") -> str:
    """Insère une contribution par paire (publication, personne) que lient des signatures, et absente de la table.

    Une paire rejetée est écartée, sauf si une signature confirmée la relie : la confirmation vise la signature elle-même, le rejet la publication. `scope` restreint les paires (`PERSON_PUBLICATIONS_SCOPE`, `SOURCE_CONTRIBUTIONS_SCOPE`).
    """
    return f"""
        WITH all_pairs AS (
            SELECT sp.publication_id, sa.person_id,
                   bool_or(ca.source_contribution_id IS NOT NULL) AS confirmed
            FROM source_contributions sa
            JOIN source_records sp ON sp.id = sa.source_record_id
            JOIN publications pub ON pub.id = sp.publication_id
            LEFT JOIN confirmed_source_contributions ca
              ON ca.source_contribution_id = sa.id AND ca.person_id = sa.person_id
            WHERE sa.person_id IS NOT NULL {scope}
            GROUP BY sp.publication_id, sa.person_id
        )
        INSERT INTO contributions (publication_id, person_id)
        SELECT ap.publication_id, ap.person_id
        FROM all_pairs ap
        WHERE NOT EXISTS (
            SELECT 1 FROM contributions a
            WHERE a.publication_id = ap.publication_id
              AND a.person_id = ap.person_id
        )
          AND (ap.confirmed
               OR NOT {publication_rejected_for("ap.publication_id", "ap.person_id")})
    """


def propagate_contribution_attributes_sql(*, scope: str = "") -> str:
    """Recompose les attributs de chaque contribution depuis ses signatures.

    La position vient de la source la plus prioritaire qui en donne une. L'auteur est correspondant si une signature le dit. Les indices de périmètre et les rôles sont l'union de ceux des signatures. `scope` restreint les paires (`PERSON_PUBLICATIONS_SCOPE`, `SOURCE_CONTRIBUTIONS_SCOPE`).
    """
    return f"""
        WITH linked AS (
            SELECT a.id AS aid, sa.source, sa.author_position, sa.is_corresponding,
                   sa.perimeter_evidence, sa.roles
            FROM source_contributions sa
            JOIN source_records sp ON sp.id = sa.source_record_id
            JOIN contributions a ON a.publication_id = sp.publication_id
                              AND a.person_id = sa.person_id
            WHERE TRUE {scope}
        ),
        scal AS (
            SELECT l.aid,
                   (array_agg(l.author_position ORDER BY
                       {case_priority(SOURCE_PRIORITY, "l.source")})
                       FILTER (WHERE l.author_position IS NOT NULL))[1] AS pos,
                   bool_or(l.is_corresponding) AS is_corr
            FROM linked l
            GROUP BY l.aid
        ),
        ev AS (
            SELECT l.aid, array_agg(DISTINCT e ORDER BY e) AS evidence
            FROM linked l, LATERAL unnest(l.perimeter_evidence) AS e
            GROUP BY l.aid
        ),
        rol AS (
            SELECT l.aid, array_agg(DISTINCT r ORDER BY r) AS roles
            FROM linked l, LATERAL unnest(l.roles) AS r
            GROUP BY l.aid
        )
        UPDATE contributions a
        SET author_position = scal.pos,
            is_corresponding = scal.is_corr,
            perimeter_evidence = coalesce(ev.evidence, {NO_PERIMETER_EVIDENCE}),
            roles            = rol.roles
        FROM scal LEFT JOIN rol ON rol.aid = scal.aid LEFT JOIN ev ON ev.aid = scal.aid
        WHERE a.id = scal.aid
          AND (a.author_position, a.is_corresponding, a.perimeter_evidence, a.roles)
              IS DISTINCT FROM (scal.pos, scal.is_corr,
                                coalesce(ev.evidence, {NO_PERIMETER_EVIDENCE}), rol.roles)
    """


def active_issns(journal: str) -> str:
    """Tableau des ISSN actifs de la revue `journal` (expression SQL), dans l'ordre d'enregistrement ; tableau vide sans ISSN."""
    return f"""coalesce((
        SELECT array_agg(i.issn ORDER BY i.id) FROM journal_issns i
        WHERE i.journal_id = {journal} AND i.status = 'active'
    ), ARRAY[]::text[])"""


def address_country_conditions(
    criteria: AddressCountryFilter,
) -> tuple[list[str], dict[str, object]]:
    """Conditions SQL de `criteria` sur l'adresse aliasée `a`, et leurs paramètres."""
    conditions: list[str] = []
    params: dict[str, object] = {}
    if criteria.search:
        conditions.append("unaccent(a.raw_text) ILIKE unaccent(:search)")
        params["search"] = f"%{criteria.search}%"
    if criteria.has_country is not None:
        conditions.append(
            "a.countries IS NOT NULL" if criteria.has_country else "a.countries IS NULL"
        )
    if criteria.country_code:
        conditions.append(":country_code = ANY(a.countries)")
        params["country_code"] = criteria.country_code
    return conditions, params


def has_active_issn(journal: str) -> str:
    """Condition vraie quand la revue `journal` a un ISSN actif."""
    return f"EXISTS (SELECT 1 FROM journal_issns i WHERE i.journal_id = {journal} AND i.status = 'active')"
