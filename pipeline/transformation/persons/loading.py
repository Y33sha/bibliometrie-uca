"""Chargement et enrichissement des candidats de la cascade personnes.

Deux populations de signatures non liées traversent la cascade (`match`/`create`) : in-périmètre (éligibles à tous les barreaux) et hors-périmètre ancrés (rattachables sans forme de nom). Ce module les charge via le port, enrichit chaque row (parsing du nom, normalisations, flag de création autorisée), et construit l'index des contributions déjà rattachées par groupe de signatures, qui alimente le signal cross-source.
"""

from collections import defaultdict
from typing import NamedTuple

from sqlalchemy import Connection, Row, text

from domain.persons.contributor_name import ContributorName
from domain.persons.creation import allow_person_creation
from domain.persons.identifiers import (
    AttributionStatus,
    PersonIdentifierType,
)
from domain.persons.matching import (
    STRONG_PERSON_IDENTIFIER_TYPES,
    ResolutionMode,
)
from domain.persons.name_forms import contributor_name_forms
from infrastructure.sql_fragments import (
    person_source_contribution,
    pinned,
    strong_identifier_source_contributions,
    usable_identifier,
)


class BareUnlinkedContribution(NamedTuple):
    """Projection SQL brute : `source_contributions` non rattaché à une personne.

    `roles` non vide en pratique uniquement pour theses (auteur vs directeur).

    `in_perimeter` reflète la détection d'une structure du périmètre sur cette signature. Les candidats `in_perimeter = FALSE` ne sont rattachables que par les barreaux non-nominaux de la cascade (identifiants forts, cross-source) — le matching/création par forme de nom reste réservé au périmètre (cf. `decide_name_form_outcome` et l'orchestrateur).
    """

    source_contribution_id: int
    source: str
    name: ContributorName
    author_name_normalized: str | None
    # `{id_type: valeur}` des identifiants de l'identité, pour chaque type de `PersonIdentifierType` présent et non neutralisé par la signature.
    identifiers: dict[str, str]
    roles: list[str] | None
    publication_id: int | None
    in_perimeter: bool
    # `person_id` courant si la signature est déjà liée en cross-source et re-jugée ce run ; `None` pour une signature non liée. Sert à diffuser l'écriture (no-op / update) et le détachement des sans-appui.
    current_person_id: int | None
    # Groupe des signatures du même auteur dans la publication (`source_contribution_group_members`) : clé du matching cross-source.
    group_id: int | None = None


class LinkedContributionRow(NamedTuple):
    """Projection SQL : `source_contributions` déjà rattaché à une personne, toutes sources confondues. Sert au matching cross-source par groupe de signatures."""

    person_id: int
    group_id: int
    name: ContributorName
    source: str


def _usable(id_type: str) -> str:
    """Valeur de l'identifiant `id_type` de la signature `sa_auth`, NULL quand elle le neutralise."""
    return usable_identifier(f"'{id_type}'", source_contribution="sa_auth")


def _to_bare(r: Row[tuple[object, ...]]) -> BareUnlinkedContribution:
    """Mappe une ligne SQL (projection partagée) vers `BareUnlinkedContribution`."""
    return BareUnlinkedContribution(
        source_contribution_id=r.source_contribution_id,
        source=r.source,
        name=ContributorName.from_columns(r.raw_author_name, r.raw_last_name, r.raw_first_name),
        author_name_normalized=r.author_name_normalized,
        identifiers=r.identifiers,
        roles=r.roles,
        publication_id=r.publication_id,
        in_perimeter=r.in_perimeter,
        current_person_id=r.current_person_id,
        group_id=r.group_id,
    )


# Colonnes communes des projections de contribution non-liée (`BareUnlinkedContribution`).
# Chaque requête y ajoute ses deux colonnes finales `in_perimeter` et `current_person_id`.
# `identifiers` porte un objet jsonb par type de `PersonIdentifierType`, sans les identifiants absents ou neutralisés par la signature.
_IDENTIFIERS_OBJECT = ", ".join(f"'{t.value}', {_usable(t.value)}" for t in PersonIdentifierType)

_BARE_PROJECTION_HEAD = f"""
    sa_auth.id AS source_contribution_id,
    sa_auth.source::text AS source,
    sa_auth.raw_author_name,
    sa_auth.raw_last_name,
    sa_auth.raw_first_name,
    aik.author_name_normalized,
    jsonb_strip_nulls(jsonb_build_object({_IDENTIFIERS_OBJECT})) AS identifiers,
    sa_auth.roles,
    sd.publication_id,
    (SELECT gs.group_id FROM source_contribution_group_members gs
     WHERE gs.source_contribution_id = sa_auth.id) AS group_id"""

_OOP_PROJECTION = f"""{_BARE_PROJECTION_HEAD},
    FALSE AS in_perimeter,
    NULL::integer AS current_person_id"""

# Conditions communes à toutes les branches : SA orpheline hors-périmètre, d'une personne,
# rattachée à une publication active (les hors périmètre ne sont pas matérialisées).
_OOP_COMMON_WHERE = f"""
    sa_auth.person_id IS NULL
    AND sa_auth.in_perimeter = FALSE
    AND {person_source_contribution("sa_auth")}
    AND sd.publication_id IS NOT NULL
"""


def _oop_identifier_branch(id_type: PersonIdentifierType) -> str:
    """Branche « identifiant-ancré » : signature hors-périmètre dont l'identifiant fort `id_type` est déjà celui d'une personne connue (non rejeté)."""
    return strong_identifier_source_contributions(
        id_type,
        identifiers="person_identifiers",
        select=_OOP_PROJECTION,
        joins="""
            JOIN source_records sd ON sd.id = sa_auth.source_record_id
            JOIN publications pub ON pub.id = sd.publication_id
        """,
        where=f"pi.status <> '{AttributionStatus.REJECTED.value}' AND {_OOP_COMMON_WHERE}",
    )


# Branche « cross-source-ancrée » : signature hors-périmètre dont le groupe (`source_contribution_group_members`) compte une signature déjà rattachée. Le matching nom-compatible est tranché côté Python (`decide_cross_source_match`).
_OOP_CROSS_SOURCE_BRANCH = f"""
    SELECT {_OOP_PROJECTION}
    FROM source_contributions linked
    JOIN source_contribution_group_members gl ON gl.source_contribution_id = linked.id
    JOIN source_contribution_group_members ga
        ON ga.group_id = gl.group_id AND ga.source_contribution_id <> gl.source_contribution_id
    JOIN source_contributions sa_auth ON sa_auth.id = ga.source_contribution_id
    JOIN source_records sd ON sd.id = sa_auth.source_record_id
    JOIN contributor_information aik ON aik.id = sa_auth.contributor_information_id
    JOIN publications pub ON pub.id = sd.publication_id
    WHERE linked.person_id IS NOT NULL
      AND {person_source_contribution("linked")}
      AND {_OOP_COMMON_WHERE}
"""

_OOP_CANDIDATES_SQL = " UNION ".join(
    [*(_oop_identifier_branch(t) for t in STRONG_PERSON_IDENTIFIER_TYPES), _OOP_CROSS_SOURCE_BRANCH]
)


def fetch_unlinked_contributions(conn: Connection) -> list[BareUnlinkedContribution]:
    """Colonnes de la projection des `source_contributions` in-perimeter, individuelles, non liées :

    - `identifiers` : identifiants de l'identité (`contributor_information`, jointe par `contributor_information_id`), sans filtre par source. Seules les signatures HAL contiennent `hal_person_id` et `idhal`. La cascade écarte les identifiants que leur source rend non fiables (`trusted_identifier`).
    """
    rows = conn.execute(
        text(f"""
            SELECT {_BARE_PROJECTION_HEAD},
                   TRUE AS in_perimeter,
                   NULL::integer AS current_person_id
            FROM source_contributions sa_auth
            JOIN contributor_information aik ON aik.id = sa_auth.contributor_information_id
            JOIN source_records sd ON sd.id = sa_auth.source_record_id
            JOIN publications pub ON pub.id = sd.publication_id
            WHERE sa_auth.person_id IS NULL
              AND sa_auth.in_perimeter = TRUE
              AND {person_source_contribution("sa_auth")}
              AND sd.publication_id IS NOT NULL
            ORDER BY sa_auth.id
        """)
    ).all()
    return [_to_bare(r) for r in rows]


def fetch_out_of_perimeter_candidates(conn: Connection) -> list[BareUnlinkedContribution]:
    """Union des quatre branches d'accès, dédupliquée en SQL (`UNION`) : une même signature peut être candidate par plusieurs chemins (identifiant fort partagé, ou ancrage cross-source sur un groupe de signatures déjà lié). La cascade côté orchestrateur arbitre ensuite (les barreaux nom/création y sont neutralisés pour ces candidats hors-périmètre).

    Seules les signatures ancrées sur une personne existante (identifiant partagé) ou sur un groupe de signatures déjà rattaché (cross-source) sont ramenées. La requête reparcourt cet ensemble à chaque run, et la branche cross-source porte l'essentiel de son coût.
    """
    rows = conn.execute(text(_OOP_CANDIDATES_SQL)).all()
    return [_to_bare(r) for r in rows]


def fetch_linked_contributions(conn: Connection) -> list[LinkedContributionRow]:
    """Sert d'index d'ancrage au matching cross-source. Les liens cross-source eux-mêmes en sont exclus (`resolution_mode <> 'cross_source'`) : un résultat cross-source n'en ancre aucun autre. Une signature collective ou un doublon d'auteur n'ancre rien."""
    rows = conn.execute(
        text(f"""
            SELECT sa_auth.person_id, gs.group_id,
                   sa_auth.raw_author_name, sa_auth.raw_last_name, sa_auth.raw_first_name,
                   sa_auth.source::text AS source
            FROM source_contributions sa_auth
            JOIN source_contribution_group_members gs ON gs.source_contribution_id = sa_auth.id
            WHERE sa_auth.person_id IS NOT NULL
              AND sa_auth.resolution_mode IS DISTINCT FROM '{ResolutionMode.CROSS_SOURCE.value}'
              AND {person_source_contribution("sa_auth")}
        """)
    ).all()
    return [
        LinkedContributionRow(
            person_id=r.person_id,
            group_id=r.group_id,
            name=ContributorName.from_columns(r.raw_author_name, r.raw_last_name, r.raw_first_name),
            source=r.source,
        )
        for r in rows
    ]


def fetch_cross_source_linked(conn: Connection) -> list[BareUnlinkedContribution]:
    """Même projection que les non-liées, plus `current_person_id` = le `person_id` courant. Une signature cross-source peut porter un identifiant ou un nom qui matche une personne existante : la ré-évaluation passe par toute la cascade, d'où les colonnes d'identifiant."""
    rows = conn.execute(
        text(f"""
            SELECT {_BARE_PROJECTION_HEAD},
                   sa_auth.in_perimeter,
                   sa_auth.person_id AS current_person_id
            FROM source_contributions sa_auth
            JOIN contributor_information aik ON aik.id = sa_auth.contributor_information_id
            JOIN source_records sd ON sd.id = sa_auth.source_record_id
            WHERE sa_auth.resolution_mode = '{ResolutionMode.CROSS_SOURCE.value}'
              AND {person_source_contribution("sa_auth")}
              AND sd.publication_id IS NOT NULL
              AND NOT {pinned("sa_auth.id")}
            ORDER BY sa_auth.id
        """)
    ).all()
    return [_to_bare(r) for r in rows]


class EnrichedContribution(NamedTuple):
    """`BareUnlinkedContribution` enrichie côté Python : nom découpé, normalisations, flag de création autorisée."""

    source_contribution_id: int
    source: str
    name: ContributorName
    author_name_normalized: str | None
    # Formes cherchées dans `person_name_forms`, ordre inversé compris (`contributor_name_forms`).
    name_forms: tuple[str, ...]
    identifiers: dict[str, str]
    publication_id: int | None
    in_perimeter: bool
    current_person_id: int | None
    last_name: str
    first_name: str
    last_norm: str
    first_norm: str
    allow_create: bool
    # Groupe des signatures du même auteur dans la publication : clé du matching cross-source.
    group_id: int | None = None


def _enrich(row: BareUnlinkedContribution) -> EnrichedContribution:
    """Découpe et normalise le nom, calcule le flag de création autorisée."""
    last_name, first_name = row.name.split()
    last_norm, first_norm = row.name.normalized()
    allow_create = allow_person_creation(row.source, row.roles or [])

    return EnrichedContribution(
        source_contribution_id=row.source_contribution_id,
        source=row.source,
        name=row.name,
        author_name_normalized=row.author_name_normalized,
        name_forms=contributor_name_forms(last_norm, first_norm),
        identifiers=row.identifiers,
        publication_id=row.publication_id,
        in_perimeter=row.in_perimeter,
        current_person_id=row.current_person_id,
        last_name=last_name,
        first_name=first_name,
        last_norm=last_norm,
        first_norm=first_norm or "",
        allow_create=allow_create,
        group_id=row.group_id,
    )


def get_all_unlinked_contributions(conn: Connection) -> list[EnrichedContribution]:
    """Charge les contributions in-périmètre sans person_id (toutes sources) et les enrichit (noms découpés, flag allow_create)."""
    return [_enrich(row) for row in fetch_unlinked_contributions(conn)]


def get_out_of_perimeter_candidates(conn: Connection) -> list[EnrichedContribution]:
    """Charge les candidats hors-périmètre rattachables sans forme de nom (identifiant fort partagé ou ancrage cross-source) et les enrichit.

    Ces candidats traversent la même cascade que les in-périmètre, mais le barreau `person_name_forms` (match unique / création) y est neutralisé : un nom seul ne peut ni introduire ni attacher une personne hors-périmètre."""
    return [_enrich(row) for row in fetch_out_of_perimeter_candidates(conn)]


def get_cross_source_candidates(conn: Connection) -> list[EnrichedContribution]:
    """Charge les signatures déjà liées **en cross-source**, à re-juger contre les ancres fermes.

    Elles portent leur `current_person_id` : la cascade compare la nouvelle décision au lien courant — même personne → no-op, différente → update, plus d'appui → détachée."""
    return [_enrich(row) for row in fetch_cross_source_linked(conn)]


def load_linked_contributions_by_group(
    conn: Connection,
) -> dict[int, list[tuple[int, str, str, str]]]:
    """Index des contributions rattachées, par groupe de signatures."""
    index: dict[int, list[tuple[int, str, str, str]]] = defaultdict(list)

    for r in fetch_linked_contributions(conn):
        ln, fn = r.name.normalized()
        index[r.group_id].append((r.person_id, ln, fn or "", r.source))

    return index
