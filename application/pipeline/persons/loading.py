"""Chargement et enrichissement des candidats de la cascade personnes.

Deux populations de signatures non liées traversent la cascade (`match`/`create`) : in-périmètre (éligibles à tous les barreaux) et hors-périmètre ancrés (rattachables sans forme de nom). Ce module les charge via le port, enrichit chaque row (parsing du nom, normalisations, flag de création autorisée), et construit l'index des authorships déjà rattachées par (publication, position) qui alimente le signal cross-source.
"""

from collections import defaultdict
from typing import NamedTuple

from sqlalchemy import Connection

from application.ports.pipeline.persons_create import (
    BareUnlinkedAuthorship,
    PersonsCreateQueries,
)
from domain.normalize import normalize_name
from domain.persons.creation import allow_person_creation
from domain.persons.name_matching import parse_raw_author_name


class EnrichedAuthorship(NamedTuple):
    """`BareUnlinkedAuthorship` enrichie côté Python : nom parsé, normalisations, flag de création autorisée."""

    authorship_id: int
    source: str
    full_name: str
    author_name_normalized: str | None
    orcid: str | None
    hal_person_id: str | None
    idref: str | None
    roles: list[str] | None
    publication_id: int | None
    author_position: int
    in_perimeter: bool
    last_name: str
    first_name: str
    last_norm: str
    first_norm: str
    allow_create: bool


def _enrich(row: BareUnlinkedAuthorship) -> EnrichedAuthorship:
    """Parse le nom, normalise, calcule le flag de création autorisée."""
    last_name, first_name = parse_raw_author_name(row.full_name)
    last_norm = normalize_name(last_name)
    first_norm = normalize_name(first_name)
    allow_create = allow_person_creation(row.source, row.roles or [])

    return EnrichedAuthorship(
        authorship_id=row.authorship_id,
        source=row.source,
        full_name=row.full_name,
        author_name_normalized=row.author_name_normalized,
        orcid=row.orcid,
        hal_person_id=row.hal_person_id,
        idref=row.idref,
        roles=row.roles,
        publication_id=row.publication_id,
        author_position=row.author_position,
        in_perimeter=row.in_perimeter,
        last_name=last_name,
        first_name=first_name,
        last_norm=last_norm,
        first_norm=first_norm,
        allow_create=allow_create,
    )


def get_all_unlinked_authorships(
    conn: Connection, queries: PersonsCreateQueries
) -> list[EnrichedAuthorship]:
    """Charge les authorships in-périmètre sans person_id (toutes sources) et les enrichit (parsing noms, flag allow_create)."""
    return [_enrich(row) for row in queries.fetch_unlinked_authorships(conn)]


def get_out_of_perimeter_candidates(
    conn: Connection, queries: PersonsCreateQueries
) -> list[EnrichedAuthorship]:
    """Charge les candidats hors-périmètre rattachables sans forme de nom (identifiant fort partagé ou ancrage cross-source) et les enrichit.

    Ces candidats traversent la même cascade que les in-périmètre, mais le barreau `person_name_forms` (match unique / création) y est neutralisé : un nom seul ne peut ni introduire ni attacher une personne hors-périmètre."""
    return [_enrich(row) for row in queries.fetch_out_of_perimeter_candidates(conn)]


def load_linked_authorships_by_pub(
    conn: Connection, queries: PersonsCreateQueries
) -> dict[tuple[int, int], list[tuple[int, str, str, str]]]:
    """Index des authorships rattachées par (publication_id, author_position)."""
    index: dict[tuple[int, int], list[tuple[int, str, str, str]]] = defaultdict(list)

    for r in queries.fetch_linked_authorships(conn):
        last, first = parse_raw_author_name(r.full_name)
        ln, fn = normalize_name(last), normalize_name(first)
        index[(r.publication_id, r.author_position)].append((r.person_id, ln, fn, r.source))

    return index
