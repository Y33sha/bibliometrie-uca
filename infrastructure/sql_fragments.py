"""Fragments SQL partagés entre plusieurs adaptateurs de l'API ou du pipeline.

Trois formes : des fragments rendus depuis des constantes du domaine (`in_clause`, `case_priority`), valeurs d'enums ou ordres de priorité, sans entrée utilisateur, donc sûrs à interpoler ; des expressions rendues depuis les alias de la requête hôte ; des expressions SQL figées.
"""

from application.ports.repositories.address_repository import AddressCountryFilter
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.persons.matching import ORCID_MATCH_SOURCES, STRONG_PERSON_IDENTIFIER_TYPES
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE
from domain.publications.contribution_roles import ContributionRole
from domain.serials.serial import OaModel
from domain.source_records.corrections import CORRECTED_BY, RAW
from domain.source_records.source_extras import CROSSREF_PREPRINT_OF, SourceExtra
from domain.sources.registry import SEARCHED_IDENTIFIER_STATUSES
from domain.structures.perimeter_evidence import PerimeterEvidence


def in_clause(values: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"


def person_source_contribution(source_contribution: str = "sc") -> str:
    """Condition vraie quand la contribution source aliasée `source_contribution` désigne une personne : elle appartient à une contribution (`aligned_source_contributions`). Les contributions sources collectives, les doublons d'auteur et celles des enregistrements sources écartés de l'alignement restent hors contribution."""
    return (
        "EXISTS (SELECT 1 FROM aligned_source_contributions gm"
        f" WHERE gm.source_contribution_id = {source_contribution}.id)"
    )


CONTRIBUTIONS_AND_SOURCES = """
    contributions g
    JOIN aligned_source_contributions gm ON gm.contribution_id = g.id
    JOIN source_contributions sc ON sc.id = gm.source_contribution_id
    JOIN contributor_information ci ON ci.id = sc.contributor_information_id
"""
"""Clause `FROM` des contributions `g` et de leurs contributions sources : contributions sources `sc`, avec leurs informations du contributeur `ci`."""


def pinned(source_contribution_id: str) -> str:
    """Condition vraie quand l'administration a épinglé la contribution source d'identifiant `source_contribution_id` à une personne (`confirmed_source_contributions`)."""
    return f"EXISTS (SELECT 1 FROM confirmed_source_contributions ca WHERE ca.source_contribution_id = {source_contribution_id})"


def active_name_form(form: str) -> str:
    """Condition vraie quand la forme de nom `form` (ligne de `person_name_forms`, ou son alias) désigne sa personne au matching : une forme dérivée du nom de la personne, ou une forme non rejetée."""
    return (
        f"({form}.status <> '{AttributionStatus.REJECTED.value}'"
        f" OR '{CANONICAL_NAME_FORM_SOURCE}' = ANY({form}.sources))"
    )


def pending_name_form(form: str) -> str:
    """Condition vraie quand la forme de nom `form` (ligne de `person_name_forms`, ou son alias) est à confirmer : en attente, hors forme dérivée du nom de la personne, qui se confirme d'office."""
    return (
        f"({form}.status = '{AttributionStatus.PENDING.value}'"
        f" AND NOT ('{CANONICAL_NAME_FORM_SOURCE}' = ANY({form}.sources)))"
    )


DETACHED_CONTRIBUTION = "person_id = NULL, resolution_mode = NULL"
"""Affectations d'un `UPDATE contributions` qui retire sa personne à une contribution."""


def diamond_journal_sql(serial: str = "j") -> str:
    """Condition vraie quand la revue aliasée `journal` est diamant : marquée `diamond`, ou présente dans le DOAJ sans APC ni autres frais. NULL quand la revue est absente d'une jointure externe."""
    return (
        f"({serial}.oa_model = '{OaModel.DIAMOND.value}' OR ({serial}.is_in_doaj"
        f" AND {serial}.doaj_payload->>'APC' = 'No'"
        f" AND {serial}.doaj_payload->>'Has other fees' = 'No'))"
    )


def has_author_role(source_contribution: str = "sc") -> str:
    """Condition vraie quand la contribution source ou la contribution aliasée `source_contribution` tient le rôle d'auteur."""
    return f"{source_contribution}.roles && ARRAY['{ContributionRole.AUTHOR.value}']::text[]"


def identifier_neutralized(
    id_type: str, source_contribution: str = "sc", *, reason: str | None = None
) -> str:
    """Condition vraie quand la contribution source aliasée `source_contribution` neutralise l'identifiant `id_type`, pour le motif `reason` s'il est donné.

    `id_type` est une expression SQL : littéral (`'orcid'`), paramètre (`:id_type`) ou colonne.
    """
    if reason is None:
        return f"coalesce({source_contribution}.neutralized_identifiers ? {id_type}, false)"
    return (
        f"coalesce({source_contribution}.neutralized_identifiers ->> {id_type} = '{reason}', false)"
    )


def usable_identifier(
    id_type: str, *, source_contribution: str = "sc", contributor_information: str = "ci"
) -> str:
    """Valeur de l'identifiant `id_type` dans les informations du contributeur d'une contribution source, NULL quand la contribution source le neutralise."""
    return (
        f"CASE WHEN {identifier_neutralized(id_type, source_contribution)} THEN NULL"
        f" ELSE {contributor_information}.identifiers ->> {id_type} END"
    )


def trusted_identifier_sql(id_type: str, source_contribution: str = "sc") -> str:
    """Condition SQL de `trusted_identifier` pour l'identifiant `id_type` de la contribution source aliasée `source_contribution`."""
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
    """Requête des contributions sources `sc_auth` dont les informations du contributeur contiennent l'identifiant `id_type` d'une ligne de `identifiers`.

    `identifiers` : table ou sous-requête, aliasée `pi`, de colonnes `person_id`, `id_type`, `id_value`. L'identifiant que la contribution source neutralise est écarté, et celui que sa source rend non fiable (`trusted_identifier_sql`). La requête rejoint les contributions sources par `contributor_information_id` après un rapprochement sur `contributor_information`.
    """
    return f"""
        SELECT {select}
        FROM {identifiers} pi
        JOIN contributor_information ci ON ci.identifiers->>'{id_type}' = pi.id_value
        JOIN source_contributions sc_auth ON sc_auth.contributor_information_id = ci.id
        {joins}
        WHERE pi.id_type = '{id_type}'
          AND ci.identifiers ? '{id_type}'
          AND NOT {identifier_neutralized(f"'{id_type}'", "sc_auth")}
          AND {trusted_identifier_sql(id_type, "sc_auth")}
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
    """Requête des ids des contributions sources qui entrent dans le périmètre par l'identifiant fort d'une personne qui a une fiche RH. La publication paraît entre l'année qui suit son arrivée et l'année de fin de son contrat, sans rejet de la personne pour l'enregistrement source.

    `source_contribution_filter` : condition supplémentaire sur la contribution source `sc_auth`.
    """
    conditions = [
        "sr_rh.publication_year BETWEEN pi.first_year AND pi.last_year",
        (
            "NOT EXISTS (SELECT 1 FROM rejected_contributions rej"
            " WHERE rej.source_record_id = sc_auth.source_record_id"
            " AND rej.person_id = pi.person_id)"
        ),
    ]
    if source_contribution_filter:
        conditions.append(source_contribution_filter)
    return " UNION ".join(
        strong_identifier_source_contributions(
            id_type,
            identifiers=_RH_IDENTIFIERS,
            select="sc_auth.id",
            joins="JOIN source_records sr_rh ON sr_rh.id = sc_auth.source_record_id",
            where=" AND ".join(conditions),
        )
        for id_type in STRONG_PERSON_IDENTIFIER_TYPES
    )


# Paires (publication, personne) rejetées : une publication est rejetée pour une personne dès qu'un de ses enregistrements sources l'est.
REJECTED_PAIRS = (
    "SELECT sr_rej.publication_id, rej.person_id FROM rejected_contributions rej"
    " JOIN source_records sr_rej ON sr_rej.id = rej.source_record_id"
)


def publication_rejected_for(publication_id: str, person_id: str) -> str:
    """Condition vraie quand la publication `publication_id` est rejetée pour la personne `person_id` (expressions SQL) : un de ses enregistrements sources l'est."""
    return (
        "EXISTS (SELECT 1 FROM rejected_contributions rej"
        " JOIN source_records sr_rej ON sr_rej.id = rej.source_record_id"
        f" WHERE sr_rej.publication_id = {publication_id} AND rej.person_id = {person_id})"
    )


# Tableau d'indices vide : hors du périmètre.
NO_PERIMETER_EVIDENCE = "'{}'::perimeter_evidence[]"


def source_contribution_perimeter_evidence(source_contribution_ids: str | None = None) -> str:
    """Requête des indices de l'entrée dans le périmètre de chaque contribution source qui en a : colonnes `id` et `evidence`, tableau trié.

    `:perimeter_ids` : structures du périmètre, atteintes par la vue matérialisée `source_contribution_structures`. `source_contribution_ids` : nom d'un paramètre lié, tableau d'ids, qui restreint les contributions sources.
    """
    by_structure = "scs.structure_id = ANY(:perimeter_ids)"
    by_contributor_information = ""
    if source_contribution_ids:
        by_structure += f" AND scs.source_contribution_id = ANY(:{source_contribution_ids})"
        by_contributor_information = f"sc_auth.id = ANY(:{source_contribution_ids})"
    return f"""
        SELECT id, array_agg(evidence ORDER BY evidence) AS evidence
        FROM (
            SELECT scs.source_contribution_id AS id, scs.evidence
            FROM source_contribution_structures scs
            WHERE {by_structure}
            UNION
            SELECT rh.id, '{PerimeterEvidence.HR_RECORD}'::perimeter_evidence
            FROM ({hr_record_source_contributions(by_contributor_information)}) rh
        ) e
        GROUP BY id
    """


def corrected(field: str, source_record: str = "sr") -> str:
    """Condition vraie quand la phase `metadata_correction` a corrigé le champ `field` de l'enregistrement source aliasé `source_record` (`domain.source_records.corrections`)."""
    return f"{source_record}.corrections ? '{field}'"


def corrected_by(field: str, source_record: str = "sr") -> str:
    """Règle qui a corrigé le champ `field` de l'enregistrement source aliasé `source_record`. NULL quand le champ est intact."""
    return f"{source_record}.corrections -> '{field}' ->> '{CORRECTED_BY}'"


def stashed_raw(field: str, source_record: str = "sr") -> str:
    """Valeur que la source donne pour le champ `field` de l'enregistrement source aliasé `source_record`, quand une correction l'a changée. NULL quand le champ est intact."""
    return f"{source_record}.corrections -> '{field}' ->> '{RAW}'"


def raw_column(field: str, source_record: str = "sr") -> str:
    """Valeur que la source donne pour la colonne texte `field` de l'enregistrement source aliasé `source_record` : la valeur conservée par une correction, sinon la colonne (`raw_value`)."""
    return (
        f"CASE WHEN {source_record}.corrections -> '{field}' ? '{RAW}'"
        f" THEN {stashed_raw(field, source_record)} ELSE {source_record}.{field} END"
    )


def source_extra(key: SourceExtra, alias: str = "sr") -> str:
    """Valeur texte de la clé `key` des champs propres à la source de la ligne aliasée `alias`, enregistrement source ou publication."""
    return f"{alias}.source_extras ->> '{key}'"


def source_extra_json(key: SourceExtra, alias: str = "sr") -> str:
    """Valeur JSON de la clé `key` des champs propres à la source de la ligne aliasée `alias`."""
    return f"{alias}.source_extras -> '{key}'"


def has_source_extra(key: SourceExtra, alias: str = "sr") -> str:
    """Condition vraie quand les champs propres à la source de la ligne aliasée `alias` contiennent la clé `key`."""
    return f"{alias}.source_extras ? '{key}'"


def declares_conference_sql(alias: str = "sr") -> str:
    """Condition vraie quand l'enregistrement source aliasé `alias` nomme son congrès (`declares_conference`)."""
    return f"COALESCE({has_source_extra(SourceExtra.CONFERENCE, alias)}, false)"


def self_declared_preprint_sql(alias: str = "sr") -> str:
    """Condition vraie quand l'enregistrement source aliasé `alias` déclare être le preprint d'une autre œuvre."""
    return f"COALESCE(jsonb_exists({source_extra_json(SourceExtra.RELATION, alias)}, '{CROSSREF_PREPRINT_OF}'), false)"


def propagate_contribution_attributes_sql(contribution_ids: str) -> str:
    """Recompose les attributs des contributions de la requête `group_ids` depuis leurs contributions sources : correspondant si une contribution source le dit, union des rôles et des indices de périmètre. Seules les contributions dont un attribut change sont écrites."""
    return f"""
        WITH members AS (
            SELECT gm.contribution_id, sc.is_corresponding, sc.perimeter_evidence, sc.roles
            FROM aligned_source_contributions gm
            JOIN source_contributions sc ON sc.id = gm.source_contribution_id
            WHERE gm.contribution_id IN ({contribution_ids})
        ),
        scal AS (
            SELECT contribution_id, bool_or(is_corresponding) AS is_corr FROM members GROUP BY contribution_id
        ),
        ev AS (
            SELECT m.contribution_id, array_agg(DISTINCT e ORDER BY e) AS evidence
            FROM members m, LATERAL unnest(m.perimeter_evidence) AS e
            GROUP BY m.contribution_id
        ),
        rol AS (
            SELECT m.contribution_id, array_agg(DISTINCT r ORDER BY r) AS roles
            FROM members m, LATERAL unnest(m.roles) AS r
            GROUP BY m.contribution_id
        )
        UPDATE contributions g
        SET is_corresponding = scal.is_corr,
            perimeter_evidence = coalesce(ev.evidence, {NO_PERIMETER_EVIDENCE}),
            roles = rol.roles
        FROM scal LEFT JOIN rol ON rol.contribution_id = scal.contribution_id LEFT JOIN ev ON ev.contribution_id = scal.contribution_id
        WHERE g.id = scal.contribution_id
          AND (g.is_corresponding, g.perimeter_evidence, g.roles)
              IS DISTINCT FROM (scal.is_corr, coalesce(ev.evidence, {NO_PERIMETER_EVIDENCE}), rol.roles)
    """


def pinned_contributions_sql(contribution_ids: str) -> tuple[str, str]:
    """Deux requêtes, à jouer dans l'ordre, qui rattachent à la personne épinglée les contributions de la requête `group_ids` dont une contribution source est épinglée.

    Une contribution dont les contributions sources sont épinglées à plusieurs personnes reste en l'état. Dans une publication, une contribution par personne au plus : une contribution épinglée cède devant une autre contribution manuelle de la même personne, et prend sa personne à une autre contribution non manuelle. La première requête libère ces autres contributions, la seconde rattache les contributions épinglées en mode `manual`.
    """
    target = f"""
        WITH pinned AS (
            SELECT gm.contribution_id, min(c.person_id) AS person_id
            FROM confirmed_source_contributions c
            JOIN aligned_source_contributions gm
                ON gm.source_contribution_id = c.source_contribution_id
            WHERE gm.contribution_id IN ({contribution_ids})
            GROUP BY gm.contribution_id
            HAVING count(DISTINCT c.person_id) = 1
        ),
        target AS (
            SELECT DISTINCT ON (g.publication_id, p.person_id) g.id, g.publication_id, p.person_id
            FROM pinned p
            JOIN contributions g ON g.id = p.contribution_id
            WHERE NOT EXISTS (
                SELECT 1 FROM contributions o
                WHERE o.publication_id = g.publication_id AND o.person_id = p.person_id
                  AND o.id <> g.id AND o.resolution_mode = 'manual'
            )
            ORDER BY g.publication_id, p.person_id, g.id
        )
    """
    release = f"""{target}
        UPDATE contributions o
        SET {DETACHED_CONTRIBUTION}
        FROM target t
        WHERE o.publication_id = t.publication_id AND o.person_id = t.person_id AND o.id <> t.id
    """
    attach = f"""{target}
        UPDATE contributions g
        SET person_id = t.person_id, resolution_mode = 'manual'
        FROM target t
        WHERE g.id = t.id
          AND (g.person_id, g.resolution_mode) IS DISTINCT FROM (t.person_id, 'manual'::resolution_mode)
    """
    return release, attach


def active_issns(serial: str) -> str:
    """Tableau des ISSN actifs de la revue `journal` (expression SQL), dans l'ordre d'enregistrement ; tableau vide sans ISSN."""
    return f"""coalesce((
        SELECT array_agg(i.issn ORDER BY i.id) FROM serial_issns i
        WHERE i.serial_id = {serial} AND i.status = 'active'
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


def has_active_issn(serial: str) -> str:
    """Condition vraie quand la revue `journal` a un ISSN actif."""
    return f"EXISTS (SELECT 1 FROM serial_issns i WHERE i.serial_id = {serial} AND i.status = 'active')"
