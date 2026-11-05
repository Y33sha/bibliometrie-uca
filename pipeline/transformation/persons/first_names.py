"""Complétion des prénoms réduits à des initiales, d'après les contributions sources des contributions rattachées aux personnes.

Une personne créée depuis une contribution source « Tnourji, A. » a le prénom « A. ». Quand les contributions sources de ses contributions lui donnent un seul prénom plein compatible (« Abdellah »), elle prend ce prénom. Le rattachement par initiales compatibles lui attribue ensuite seulement les contributions sources de ce prénom. Avec plusieurs prénoms pleins compatibles, elle garde ses initiales (`Namesake.conflicting`).
"""

from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.persons.contributor_name import ContributorName
from domain.persons.name_matching import first_name_initials
from domain.persons.source_contribution_matching import Namesake, attested_full_first_names
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import CONTRIBUTIONS_AND_SOURCES
from pipeline.transformation.persons.store import fetch_namesakes


def fetch_linked_contributor_names(
    conn: Connection, person_ids: list[int]
) -> dict[int, list[ContributorName]]:
    """Renvoie `{person_id: [nom, ...]}` : les noms bruts des contributions sources des contributions rattachées à chaque personne."""
    if not person_ids:
        return {}
    rows = conn.execute(
        text(f"""
            SELECT g.person_id, sc.raw_author_name, sc.raw_last_name, sc.raw_first_name
            FROM {CONTRIBUTIONS_AND_SOURCES}
            WHERE g.person_id = ANY(:ids)
        """),
        {"ids": person_ids},
    ).all()
    names: dict[int, list[ContributorName]] = {}
    for r in rows:
        names.setdefault(r.person_id, []).append(
            ContributorName.from_columns(r.raw_author_name, r.raw_last_name, r.raw_first_name)
        )
    return names


class FirstNameCompletion(NamedTuple):
    """Issue de la complétion des prénoms."""

    completed: int
    """Nombre de personnes complétées."""
    conflicting: frozenset[int]
    """Personnes à plusieurs prénoms pleins concurrents."""


def _attested_first_names(conn: Connection) -> dict[Namesake, list[str]]:
    """Renvoie les prénoms pleins donnés par les contributions sources de leurs contributions, pour chaque personne au prénom réduit sans fiche RH qui en a."""
    reduced = {}
    for namesake in fetch_namesakes(conn):
        initials = first_name_initials(namesake.first_name)
        if initials is not None and not namesake.hr_record:
            reduced[namesake.person_id] = (namesake, initials)
    names = fetch_linked_contributor_names(conn, sorted(reduced))
    return {
        namesake: list(attested.values())
        for person_id, (namesake, initials) in reduced.items()
        if (
            attested := attested_full_first_names(
                namesake.last_name, initials, names.get(person_id, ())
            )
        )
    }


def complete_reduced_first_names(
    conn: Connection, *, repo: PgPersonRepository
) -> FirstNameCompletion:
    """Donne à chaque personne au prénom réduit le prénom plein, s'il est seul donné par les contributions sources de ses contributions. Le prénom d'une personne à fiche RH vient du SI RH et reste tel quel."""
    completed = 0
    conflicting: set[int] = set()
    for namesake, first_names in _attested_first_names(conn).items():
        if len(first_names) == 1:
            repo.rename(namesake.person_id, namesake.last_name, first_names[0])
            completed += 1
        else:
            conflicting.add(namesake.person_id)
    return FirstNameCompletion(completed, frozenset(conflicting))


def conflicting_reduced_first_names(conn: Connection) -> frozenset[int]:
    """Renvoie les personnes au prénom réduit à plusieurs prénoms pleins concurrents (`FirstNameCompletion.conflicting`), sans compléter de prénom."""
    return frozenset(
        namesake.person_id
        for namesake, first_names in _attested_first_names(conn).items()
        if len(first_names) > 1
    )
