"""Fragments SQL partagés entre plusieurs adaptateurs de l'API ou du pipeline.

Trois formes : des fragments rendus depuis des constantes du domaine (`in_clause`, `case_priority` — valeurs d'enums ou ordres de priorité, jamais d'entrée utilisateur : interpolation directe sûre), des expressions rendues depuis les alias de la requête hôte (identifiants d'une signature), et des expressions SQL figées.
"""

from application.ports.repositories.address_repository import AddressCountryFilter
from domain.journals.journal import OaModel
from domain.persons.identifiers import PersonIdentifierType
from domain.persons.matching import ORCID_MATCH_SOURCES, STRONG_IDENTIFIER_TYPES
from domain.publications.authorship_roles import AuthorshipRole
from domain.sources.person_search import SEARCHED_IDENTIFIER_STATUSES
from domain.structures.perimeter_evidence import PerimeterEvidence


def in_clause(values: tuple[str, ...]) -> str:
    """Contenu d'une clause SQL `IN` : `('a', 'b', …)`, prêt à interpoler dans `col IN {...}`."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def case_priority(values: tuple[str, ...], col: str) -> str:
    """Fragment `CASE <col> WHEN 'v1' THEN 1 … END` classant `col` par l'ordre de `values`, pour un `ORDER BY` ou un `array_agg(… ORDER BY …)`."""
    whens = " ".join(f"WHEN '{v}' THEN {i + 1}" for i, v in enumerate(values))
    return f"CASE {col} {whens} END"


def diamond_journal_sql(journal: str = "j") -> str:
    """Condition vraie quand la revue aliasée `journal` est diamant : marquée `diamond`, ou présente dans le DOAJ sans APC ni autres frais. NULL quand la revue est absente d'une jointure externe."""
    return (
        f"({journal}.oa_model = '{OaModel.DIAMOND.value}' OR ({journal}.is_in_doaj"
        f" AND {journal}.doaj_payload->>'APC' = 'No'"
        f" AND {journal}.doaj_payload->>'Has other fees' = 'No'))"
    )


def has_author_role(signature: str = "sa") -> str:
    """Condition vraie quand la signature ou l'authorship aliasée `signature` tient le rôle d'auteur."""
    return f"{signature}.roles && ARRAY['{AuthorshipRole.AUTHOR.value}']::text[]"


def identifier_neutralized(
    id_type: str, signature: str = "sa", *, reason: str | None = None
) -> str:
    """Condition vraie quand la signature aliasée `signature` neutralise l'identifiant `id_type`, pour le motif `reason` s'il est donné.

    `id_type` est une expression SQL : littéral (`'orcid'`), paramètre (`:id_type`) ou colonne.
    """
    if reason is None:
        return f"coalesce({signature}.neutralized_identifiers ? {id_type}, false)"
    return f"coalesce({signature}.neutralized_identifiers ->> {id_type} = '{reason}', false)"


def usable_identifier(id_type: str, *, signature: str = "sa", identity: str = "aik") -> str:
    """Valeur de l'identifiant `id_type` dans l'identité d'une signature, NULL quand la signature le neutralise."""
    return (
        f"CASE WHEN {identifier_neutralized(id_type, signature)} THEN NULL"
        f" ELSE {identity}.person_identifiers ->> {id_type} END"
    )


def strong_identifier_signatures(
    id_type: PersonIdentifierType,
    *,
    identifiers: str,
    select: str,
    joins: str = "",
    where: str = "",
) -> str:
    """Requête des signatures `sa_auth` dont l'identité contient l'identifiant `id_type` d'une ligne de `identifiers`.

    `identifiers` : table ou sous-requête, aliasée `pi`, de colonnes `person_id`, `id_type`, `id_value`. L'identifiant que la signature neutralise est écarté, et l'ORCID des sources hors `ORCID_MATCH_SOURCES`. La requête rejoint les signatures par `identity_id` après un rapprochement sur `author_identifying_keys`.
    """
    orcid_sources = (
        f"AND sa_auth.source::text IN {in_clause(tuple(sorted(ORCID_MATCH_SOURCES)))}"
        if id_type == PersonIdentifierType.ORCID
        else ""
    )
    return f"""
        SELECT {select}
        FROM {identifiers} pi
        JOIN author_identifying_keys aik ON aik.person_identifiers->>'{id_type}' = pi.id_value
        JOIN source_authorships sa_auth ON sa_auth.identity_id = aik.id
        {joins}
        WHERE pi.id_type = '{id_type}'
          AND aik.person_identifiers ? '{id_type}'
          AND NOT {identifier_neutralized(f"'{id_type}'", "sa_auth")}
          {orcid_sources}
          {f"AND {where}" if where else ""}
    """


# Identifiants des personnes RH, aux statuts qui les font interroger, avec les années de début et de fin de contrat. Une date inconnue ne borne pas : 0 sans début, 9999 sans fin.
_RH_IDENTIFIERS = f"""(
    SELECT pi.person_id, pi.id_type::text AS id_type, pi.id_value,
           coalesce(extract(year FROM r.start_date)::int, 0) AS first_year,
           coalesce(extract(year FROM r.end_date)::int, 9999) AS last_year
    FROM person_identifiers pi
    JOIN persons_rh r ON r.person_id = pi.person_id
    WHERE pi.status::text IN {in_clause(tuple(sorted(SEARCHED_IDENTIFIER_STATUSES)))}
)"""


def rh_identity_signatures(signature_filter: str = "") -> str:
    """Requête des ids des signatures qui entrent dans le périmètre par l'identité : identifiant fort d'une personne RH, document paru entre les années de début et de fin de son contrat, sans rejet de la personne pour la notice.

    `signature_filter` : condition supplémentaire sur la signature `sa_auth`.
    """
    conditions = [
        "sp_rh.pub_year BETWEEN pi.first_year AND pi.last_year",
        (
            "NOT EXISTS (SELECT 1 FROM rejected_authorships rej"
            " WHERE rej.source_publication_id = sa_auth.source_publication_id"
            " AND rej.person_id = pi.person_id)"
        ),
    ]
    if signature_filter:
        conditions.append(signature_filter)
    return " UNION ".join(
        strong_identifier_signatures(
            id_type,
            identifiers=_RH_IDENTIFIERS,
            select="sa_auth.id",
            joins="JOIN source_publications sp_rh ON sp_rh.id = sa_auth.source_publication_id",
            where=" AND ".join(conditions),
        )
        for id_type in STRONG_IDENTIFIER_TYPES
    )


# Paires (publication, personne) rejetées : une publication est rejetée pour une personne dès qu'une de ses notices l'est.
REJECTED_PAIRS = (
    "SELECT sp_rej.publication_id, rej.person_id FROM rejected_authorships rej"
    " JOIN source_publications sp_rej ON sp_rej.id = rej.source_publication_id"
)


def publication_rejected_for(publication_id: str, person_id: str) -> str:
    """Condition vraie quand la publication `publication_id` est rejetée pour la personne `person_id` (expressions SQL) : une de ses notices l'est."""
    return (
        "EXISTS (SELECT 1 FROM rejected_authorships rej"
        " JOIN source_publications sp_rej ON sp_rej.id = rej.source_publication_id"
        f" WHERE sp_rej.publication_id = {publication_id} AND rej.person_id = {person_id})"
    )


# Tableau d'indices vide : hors du périmètre.
NO_PERIMETER_EVIDENCE = "'{}'::perimeter_evidence[]"


def signature_perimeter_evidence(signature_ids: str | None = None) -> str:
    """Requête des indices de l'entrée dans le périmètre de chaque signature qui en a : colonnes `id` et `evidence`, tableau trié.

    `:perimeter_ids` : structures du périmètre, atteintes par la matview `source_authorship_structures`. `signature_ids` : nom d'un paramètre lié, tableau d'ids, qui restreint les signatures.
    """
    by_structure = "sas.structure_id = ANY(:perimeter_ids)"
    by_identity = ""
    if signature_ids:
        by_structure += f" AND sas.source_authorship_id = ANY(:{signature_ids})"
        by_identity = f"sa_auth.id = ANY(:{signature_ids})"
    return f"""
        SELECT id, array_agg(evidence ORDER BY evidence) AS evidence
        FROM (
            SELECT sas.source_authorship_id AS id, sas.evidence
            FROM source_authorship_structures sas
            WHERE {by_structure}
            UNION
            SELECT rh.id, '{PerimeterEvidence.RH_IDENTITY}'::perimeter_evidence
            FROM ({rh_identity_signatures(by_identity)}) rh
        ) e
        GROUP BY id
    """


# Indices de l'authorship aliasée `a` : union des indices de ses signatures.
AUTHORSHIP_PERIMETER_EVIDENCE_EXPR = f"""
    coalesce((
        SELECT array_agg(DISTINCT e ORDER BY e)
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        CROSS JOIN LATERAL unnest(sa.perimeter_evidence) e
        WHERE sd.publication_id = a.publication_id
          AND sa.person_id = a.person_id
    ), {NO_PERIMETER_EVIDENCE})
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
