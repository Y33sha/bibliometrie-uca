"""Fragments SQL partagés entre plusieurs adaptateurs de l'API ou du pipeline.

Le module contient des fragments construits depuis des constantes du domaine (`in_clause`, `case_priority`), des expressions construites depuis les alias de la requête hôte, et des expressions SQL figées. Les constantes du domaine (valeurs d'enums, ordres de priorité) sont sans entrée utilisateur, donc sûres à interpoler.
"""

from collections.abc import Iterable

from application.ports.repositories.address_repository import AddressCountryFilter
from domain.addresses.address_origin import AddressOrigin
from domain.config import ConfigKey
from domain.contributions.author_positions import SCANR_TRUNCATED_LENGTHS, AuthorPosition
from domain.contributions.contribution_roles import ContributionRole
from domain.persons.contribution_matching import ContributionMatchReason
from domain.persons.identifiers import (
    HUMAN_ATTRIBUTION_STATUSES,
    AttributionStatus,
    PersonIdentifierType,
)
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE
from domain.persons.source_contribution_matching import (
    ORCID_MATCH_SOURCES,
    STRONG_PERSON_IDENTIFIER_TYPES,
)
from domain.serials.serial import OaModel
from domain.source_records.corrections import CORRECTED_BY, RAW
from domain.source_records.impact import CitationTop
from domain.source_records.source_extras import CROSSREF_PREPRINT_OF, SourceExtra
from domain.structures.perimeter_evidence import PerimeterEvidence
from infrastructure.db.queues import Queue, enqueue_sql


def in_clause(values: Iterable[str]) -> str:
    """Renvoie le contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`. Les valeurs sont triées : le texte de la requête est stable."""
    return "(" + ", ".join(f"'{v}'" for v in sorted(values)) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Renvoie le fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"


def person_source_contribution(source_contribution: str = "sc") -> str:
    """Renvoie la condition vraie quand la contribution source aliasée `source_contribution` désigne une personne, donc appartient à une contribution (`aligned_source_contributions`).

    Les contributions sources collectives, les doublons d'auteur et les contributions sources des enregistrements sources écartés de l'alignement restent hors contribution.
    """
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
    """Renvoie la condition vraie quand l'administration a épinglé la contribution source d'identifiant `source_contribution_id` à une personne (`confirmed_source_contributions`)."""
    return f"EXISTS (SELECT 1 FROM confirmed_source_contributions ca WHERE ca.source_contribution_id = {source_contribution_id})"


def active_name_form(form: str) -> str:
    """Renvoie la condition vraie quand la forme de nom `form` (ligne de `person_name_forms`, ou son alias) désigne sa personne au matching : une forme dérivée du nom de la personne, ou une forme non rejetée."""
    return (
        f"({form}.status <> '{AttributionStatus.REJECTED.value}'"
        f" OR '{CANONICAL_NAME_FORM_SOURCE}' = ANY({form}.sources))"
    )


def pending_name_form(form: str) -> str:
    """Renvoie la condition vraie quand la forme de nom `form` (ligne de `person_name_forms`, ou son alias) est à confirmer : en attente, hors forme dérivée du nom de la personne, confirmée d'office."""
    return (
        f"({form}.status = '{AttributionStatus.PENDING.value}'"
        f" AND NOT ('{CANONICAL_NAME_FORM_SOURCE}' = ANY({form}.sources)))"
    )


DETACHED_CONTRIBUTION = "person_id = NULL, resolution_mode = NULL"
"""Affectations d'un `UPDATE contributions` détachant une contribution de sa personne."""


def diamond_journal_sql(serial: str = "j") -> str:
    """Renvoie la condition vraie quand la revue aliasée `serial` est diamant. NULL quand la revue est absente d'une jointure externe."""
    return f"({serial}.oa_model = '{OaModel.DIAMOND.value}')"


def is_laboratory(structure: str = "s") -> str:
    """Renvoie la condition vraie quand la structure aliasée `structure` est d'un type traité comme laboratoire (clé de config `laboratory_types`). La liste des types se calcule une fois par requête."""
    return (
        f"{structure}.structure_type = ANY(ARRAY(SELECT jsonb_array_elements_text("
        f"(SELECT value FROM config WHERE key = '{ConfigKey.LABORATORY_TYPES}')"
        "))::structure_type[])"
    )


def is_raw_address(address: str = "a") -> str:
    """Renvoie la condition vraie quand l'adresse aliasée `address` est une adresse brute. Une adresse sans origine en est exclue."""
    return f"{address}.origin = '{AddressOrigin.RAW.value}'"


def has_author_role(source_contribution: str = "sc") -> str:
    """Renvoie la condition vraie quand la contribution source ou la contribution aliasée `source_contribution` tient le rôle d'auteur."""
    return f"{source_contribution}.roles && ARRAY['{ContributionRole.AUTHOR.value}']::text[]"


def has_author_position(position: AuthorPosition, contribution: str = "a") -> str:
    """Renvoie la condition vraie quand la contribution aliasée `contribution` occupe la position d'auteur `position`."""
    return f"'{position}' = ANY({contribution}.author_positions)"


def identifier_neutralized(
    id_type: str, source_contribution: str = "sc", *, reason: str | None = None
) -> str:
    """Renvoie la condition vraie quand la contribution source aliasée `source_contribution` neutralise l'identifiant `id_type`, pour le motif `reason` s'il est donné.

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
    """Renvoie la valeur de l'identifiant `id_type` dans les informations du contributeur d'une contribution source, NULL quand la contribution source le neutralise."""
    return (
        f"CASE WHEN {identifier_neutralized(id_type, source_contribution)} THEN NULL"
        f" ELSE {contributor_information}.identifiers ->> {id_type} END"
    )


def trusted_identifier_sql(id_type: str, source_contribution: str = "sc") -> str:
    """Renvoie la condition SQL de `trusted_identifier` pour l'identifiant `id_type` de la contribution source aliasée `source_contribution`."""
    if id_type != PersonIdentifierType.ORCID:
        return "TRUE"
    return f"{source_contribution}.source::text IN {in_clause(ORCID_MATCH_SOURCES)}"


def strong_identifier_source_contributions(
    id_type: PersonIdentifierType,
    *,
    identifiers: str,
    select: str,
    joins: str = "",
    where: str = "",
) -> str:
    """Renvoie la requête des contributions sources `sc_auth` dont les informations du contributeur contiennent l'identifiant `id_type` d'une ligne de `identifiers`.

    Un identifiant neutralisé par la contribution source est écarté, comme un identifiant non fiable pour sa source (`trusted_identifier_sql`). La jointure passe par `contributor_information`, puis par `contributor_information_id`.

    Args:
        identifiers: table ou sous-requête, aliasée `pi`, de colonnes `person_id`, `id_type`, `id_value`.
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


# Intervalles de présence continue d'une personne, toutes unités confondues : une période ouvre un intervalle quand elle commence plus d'un jour après la fin de toutes les précédentes. Une date absente est une borne ouverte.
_HR_PRESENCE = """(
    SELECT person_id, min(start_date) AS start_date,
           CASE WHEN bool_or(end_date IS NULL) THEN NULL ELSE max(end_date) END AS end_date
    FROM (
        SELECT *, sum(opens) OVER (PARTITION BY person_id ORDER BY start_date NULLS FIRST, id) AS span
        FROM (
            SELECT id, person_id, start_date, end_date,
                   CASE WHEN start_date <= max(coalesce(end_date, 'infinity'::date)) OVER (
                            PARTITION BY person_id ORDER BY start_date NULLS FIRST, id
                            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                        ) + 1
                        THEN 0 ELSE 1 END AS opens
            FROM hr_periods
        ) periods
    ) numbered
    GROUP BY person_id, span
)"""

# Identifiants des personnes RH, aux statuts interrogés, avec les années de présence de chaque intervalle : de l'année qui suit le début à l'année de fin. Sans date : 0, 9999.
_RH_IDENTIFIERS = f"""(
    SELECT pi.person_id, pi.id_type::text AS id_type, pi.id_value,
           coalesce(extract(year FROM r.start_date)::int + 1, 0) AS first_year,
           coalesce(extract(year FROM r.end_date)::int, 9999) AS last_year
    FROM person_identifiers pi
    JOIN {_HR_PRESENCE} r ON r.person_id = pi.person_id
    WHERE pi.status::text IN {in_clause(HUMAN_ATTRIBUTION_STATUSES)}
)"""


def hr_record_source_contributions(source_contribution_filter: str = "") -> str:
    """Renvoie la requête des ids des contributions sources entrées dans le périmètre par l'identifiant fort d'une personne à fiche RH.

    La publication paraît pendant un intervalle de présence de la personne, de l'année suivant son début à l'année de sa fin. La personne est sans rejet pour l'enregistrement source.

    Args:
        source_contribution_filter: condition supplémentaire sur la contribution source `sc_auth`.
    """
    conditions = [
        "sr_rh.publication_year BETWEEN pi.first_year AND pi.last_year",
        (
            "NOT EXISTS (SELECT 1 FROM rejected_contributions rej"
            " WHERE rej.source = sr_rh.source AND rej.source_id = sr_rh.source_id"
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


# Rejets `rej` et leurs enregistrements sources présents `sr_rej`, par clé naturelle. Un rejet sans enregistrement source présent reste en sommeil.
_REJECTIONS = (
    "rejected_contributions rej"
    " JOIN source_records sr_rej ON sr_rej.source = rej.source AND sr_rej.source_id = rej.source_id"
)

# Paires (publication, personne) rejetées : une publication est rejetée pour une personne dès qu'un de ses enregistrements sources l'est.
REJECTED_PAIRS = f"SELECT sr_rej.publication_id, rej.person_id FROM {_REJECTIONS}"


def publication_rejected_for(publication_id: str, person_id: str) -> str:
    """Renvoie la condition vraie quand la publication `publication_id` est rejetée pour la personne `person_id` (expressions SQL) : un de ses enregistrements sources l'est."""
    return (
        f"EXISTS (SELECT 1 FROM {_REJECTIONS}"
        f" WHERE sr_rej.publication_id = {publication_id} AND rej.person_id = {person_id})"
    )


# Tableau d'indices vide : hors du périmètre.
NO_PERIMETER_EVIDENCE = "'{}'::perimeter_evidence[]"

# Tableau de positions d'auteur vide.
NO_AUTHOR_POSITION = "'{}'::author_position[]"


def source_contribution_perimeter_evidence(source_contribution_ids: str | None = None) -> str:
    """Renvoie la requête des indices de l'entrée dans le périmètre, par contribution source : colonnes `id` et `evidence`, tableau trié.

    Le paramètre lié `:perimeter_ids` désigne les structures du périmètre, atteintes par la vue matérialisée `source_contribution_structures`.

    Args:
        source_contribution_ids: nom d'un paramètre lié, tableau d'ids restreignant les contributions sources.
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
    """Renvoie la condition vraie quand la phase `metadata_correction` a corrigé le champ `field` de l'enregistrement source aliasé `source_record` (`domain.source_records.corrections`)."""
    return f"{source_record}.corrections ? '{field}'"


def corrected_by(field: str, source_record: str = "sr") -> str:
    """Renvoie la règle de correction du champ `field` de l'enregistrement source aliasé `source_record`. NULL quand le champ est intact."""
    return f"{source_record}.corrections -> '{field}' ->> '{CORRECTED_BY}'"


def stashed_raw(field: str, source_record: str = "sr") -> str:
    """Renvoie la valeur donnée par la source pour le champ `field` de l'enregistrement source aliasé `source_record`, avant correction. NULL quand le champ est intact."""
    return f"{source_record}.corrections -> '{field}' ->> '{RAW}'"


def source_extra(key: SourceExtra, alias: str = "sr") -> str:
    """Renvoie la valeur texte de la clé `key` des champs propres à la source de la ligne aliasée `alias`, enregistrement source ou publication."""
    return f"{alias}.source_extras ->> '{key}'"


def source_extra_json(key: SourceExtra, alias: str = "sr") -> str:
    """Renvoie la valeur JSON de la clé `key` des champs propres à la source de la ligne aliasée `alias`."""
    return f"{alias}.source_extras -> '{key}'"


def has_source_extra(key: SourceExtra, alias: str = "sr") -> str:
    """Renvoie la condition vraie quand les champs propres à la source de la ligne aliasée `alias` contiennent la clé `key`."""
    return f"{alias}.source_extras ? '{key}'"


def cited_by_count(alias: str = "p") -> str:
    """Renvoie le nombre de citations de la ligne aliasée `alias`, publication ou enregistrement source. NULL sans indicateur."""
    return f"({alias}.impact ->> 'cited_by_count')::int"


def fwci(alias: str = "p") -> str:
    """Renvoie le FWCI de la ligne aliasée `alias`, publication ou enregistrement source. NULL sans indicateur."""
    return f"({alias}.impact ->> 'fwci')::float8"


def reaches_citation_top(top: CitationTop, alias: str = "p") -> str:
    """Renvoie la condition vraie quand la ligne aliasée `alias`, publication ou enregistrement source, atteint le seuil de citation `top`. Sans indicateur, la condition est fausse."""
    return f"COALESCE(({alias}.impact ->> '{top}')::boolean, FALSE)"


def under_active_embargo(source_record: str = "sr") -> str:
    """Condition SQL : l'enregistrement source `source_record` est sous un embargo actif, à date de fin future ou sans date (`embargoes`)."""
    return (
        f"EXISTS (SELECT 1 FROM embargoes e WHERE e.source_record_id = {source_record}.id"
        " AND (e.until IS NULL OR e.until > current_date))"
    )


def declares_conference_sql(alias: str = "sr") -> str:
    """Renvoie la condition vraie quand l'enregistrement source aliasé `alias` nomme son congrès (`declares_conference`)."""
    return f"COALESCE({has_source_extra(SourceExtra.CONFERENCE, alias)}, false)"


def self_declared_preprint_sql(alias: str = "sr") -> str:
    """Renvoie la condition vraie quand l'enregistrement source aliasé `alias` déclare être le preprint d'une autre œuvre."""
    return f"COALESCE(jsonb_exists({source_extra_json(SourceExtra.RELATION, alias)}, '{CROSSREF_PREPRINT_OF}'), false)"


def propagate_contribution_attributes_sql(contribution_ids: str) -> str:
    """Renvoie l'instruction recomposant les attributs des contributions de la requête `contribution_ids` depuis leurs contributions sources.

    Ses rôles et ses indices de périmètre sont l'union de ceux de ses contributions sources. Ses positions d'auteur (`AuthorPosition`) :

    - `corresponding` : une de ses contributions sources est correspondante ;
    - `first` : la contribution reçoit la majorité des votes des listes d'auteurs pour le premier rang ;
    - `last` : la contribution reçoit la majorité des votes des listes d'auteurs complètes pour le dernier rang.

    La liste d'auteurs d'un enregistrement source réunit ses contributions sources individuelles au rôle d'auteur, hors doublons, avec une position. Une liste est tronquée si une autre liste de sa publication est plus longue et si elle compte un seul auteur, ou une longueur de `SCANR_TRUNCATED_LENGTHS` pour scanR. La copie scanR d'un dépôt HAL vote seulement en l'absence de l'enregistrement HAL. Une égalité laisse la publication sans premier ou sans dernier auteur. Seules les contributions à attribut changé sont écrites.

    Une contribution rattachée sans épinglage qui quitte le périmètre est marquée pour la redécision de sa personne. L'instruction renvoie le nombre de contributions écrites.
    """
    left_perimeter = enqueue_sql(
        Queue.CONTRIBUTION_RESOLUTION,
        "SELECT id FROM updated WHERE was_in AND NOT is_in AND person_id IS NOT NULL"
        f" AND resolution_mode <> '{ContributionMatchReason.MANUAL}'",
    )
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
        ),
        author_lists AS (
            SELECT sr.id AS source_record_id, sr.publication_id, sr.source, sr.source_id,
                   count(*) AS length,
                   max(count(*)) OVER (PARTITION BY sr.publication_id) AS longest,
                   min(sc.author_position) AS first_position, max(sc.author_position) AS last_position
            FROM source_records sr
            JOIN source_contributions sc ON sc.source_record_id = sr.id
            -- `DISTINCT` donne au planificateur une estimation juste du nombre de publications. Il lit donc les contributions sources par l'index.
            WHERE sr.publication_id IN (SELECT DISTINCT publication_id FROM contributions WHERE id IN ({contribution_ids}))
              AND {has_author_role("sc")} AND NOT sc.collective
              AND sc.duplicate_of IS NULL AND sc.author_position IS NOT NULL
            GROUP BY sr.id
        ),
        voting_lists AS (
            SELECT l.source_record_id, l.publication_id, l.first_position, l.last_position,
                   l.length < l.longest
                   AND (l.length = 1 OR (l.source = 'scanr' AND l.length IN ({", ".join(map(str, SCANR_TRUNCATED_LENGTHS))})))
                       AS truncated
            FROM author_lists l
            -- L'identifiant scanR d'une copie de dépôt HAL est l'identifiant HAL préfixé de `hal`.
            WHERE NOT (l.source = 'scanr' AND EXISTS (
                SELECT 1 FROM source_records h
                WHERE h.publication_id = l.publication_id AND h.source = 'hal' AND 'hal' || h.source_id = l.source_id
            ))
        ),
        votes AS (
            SELECT v.source_record_id, v.publication_id, p.position, gm.contribution_id
            FROM voting_lists v
            CROSS JOIN LATERAL (VALUES
                ('{AuthorPosition.FIRST}'::author_position, v.first_position),
                ('{AuthorPosition.LAST}'::author_position, CASE WHEN NOT v.truncated THEN v.last_position END)
            ) AS p (position, author_position)
            JOIN source_contributions sc
              ON sc.source_record_id = v.source_record_id AND sc.author_position = p.author_position
            LEFT JOIN aligned_source_contributions gm ON gm.source_contribution_id = sc.id
        ),
        tally AS (
            -- Une contribution source hors contribution compte comme un candidat distinct, jamais élu.
            SELECT publication_id, position, contribution_id,
                   rank() OVER (PARTITION BY publication_id, position ORDER BY count(*) DESC) AS rank
            FROM votes
            GROUP BY publication_id, position, contribution_id,
                     CASE WHEN contribution_id IS NULL THEN source_record_id END
        ),
        elected AS (
            SELECT min(contribution_id) AS contribution_id, position
            FROM tally WHERE rank = 1
            GROUP BY publication_id, position
            HAVING count(*) = 1
        ),
        pos AS (
            SELECT contribution_id, array_agg(position ORDER BY position) AS positions
            FROM (
                SELECT contribution_id, position FROM elected
                WHERE contribution_id IN ({contribution_ids})
                UNION ALL
                SELECT contribution_id, '{AuthorPosition.CORRESPONDING}'::author_position FROM scal WHERE is_corr
            ) AS p
            GROUP BY contribution_id
        ),
        updated AS (
            UPDATE contributions g
            SET author_positions = coalesce(pos.positions, {NO_AUTHOR_POSITION}),
                perimeter_evidence = coalesce(ev.evidence, {NO_PERIMETER_EVIDENCE}),
                roles = rol.roles
            FROM scal
            LEFT JOIN rol ON rol.contribution_id = scal.contribution_id
            LEFT JOIN ev ON ev.contribution_id = scal.contribution_id
            LEFT JOIN pos ON pos.contribution_id = scal.contribution_id
            WHERE g.id = scal.contribution_id
              AND (g.author_positions, g.perimeter_evidence, g.roles)
                  IS DISTINCT FROM (coalesce(pos.positions, {NO_AUTHOR_POSITION}), coalesce(ev.evidence, {NO_PERIMETER_EVIDENCE}), rol.roles)
            RETURNING g.id, old.in_perimeter AS was_in, new.in_perimeter AS is_in,
                      g.person_id, g.resolution_mode
        ),
        marked AS ({left_perimeter})
        SELECT count(*) FROM updated
    """


def pinned_contributions_sql(contribution_ids: str) -> tuple[str, str]:
    """Renvoie deux requêtes, à jouer dans l'ordre, rattachant à la personne épinglée les contributions de la requête `contribution_ids` à contribution source épinglée.

    Une contribution aux contributions sources épinglées à plusieurs personnes reste en l'état. Dans une publication, une personne a au plus une contribution. Une contribution épinglée cède devant une autre contribution manuelle de la même personne. Elle prend sa personne à une autre contribution non manuelle. La première requête libère ces autres contributions, la seconde rattache les contributions épinglées en mode `manual`.
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


def serial_issnl(serial: str) -> str:
    """Renvoie l'expression SQL de l'ISSN-L de la revue `serial`, `NULL` pour une revue sans ISSN. Un ISSN égal à son ISSN-L l'emporte."""
    return f"""(
        SELECT coalesce(i.issnl, i.issn) FROM serial_issns i
        WHERE i.serial_id = {serial}
        ORDER BY i.issn = i.issnl DESC NULLS LAST, i.issn
        LIMIT 1
    )"""


def active_issns(serial: str) -> str:
    """Renvoie le tableau des ISSN actifs de la revue `serial` (expression SQL), dans l'ordre d'enregistrement ; tableau vide sans ISSN."""
    return f"""coalesce((
        SELECT array_agg(i.issn ORDER BY i.id) FROM serial_issns i
        WHERE i.serial_id = {serial} AND i.status = 'active'
    ), ARRAY[]::text[])"""


def address_country_conditions(
    criteria: AddressCountryFilter,
) -> tuple[list[str], dict[str, object]]:
    """Renvoie les conditions SQL de `criteria` sur l'adresse aliasée `a`, et leurs paramètres."""
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
    """Renvoie la condition vraie quand la revue `serial` a un ISSN actif."""
    return f"EXISTS (SELECT 1 FROM serial_issns i WHERE i.serial_id = {serial} AND i.status = 'active')"
