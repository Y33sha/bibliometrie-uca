"""Complétion des prénoms réduits à des initiales, d'après les contributions sources des groupes rattachés aux personnes.

Une personne créée depuis une contribution source « Tnourji, A. » a le prénom « A. ». Quand les membres de ses groupes lui donnent un seul prénom plein compatible (« Abdellah »), elle prend ce prénom : le rattachement par initiales compatibles ne lui envoie ensuite que les contributions sources de ce prénom. Quand elles lui en donnent plusieurs, elle garde ses initiales et ne reçoit aucun prénom plein de plus (`Namesake.conflicting`).
"""

from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.persons.contributor_name import ContributorName
from domain.persons.matching import attested_full_first_names
from domain.persons.name_matching import first_name_initials
from infrastructure.repositories.person_repository import PgPersonRepository
from infrastructure.sql_fragments import GROUP_MEMBERS
from pipeline.transformation.persons.store import fetch_namesakes


def fetch_linked_contributor_names(
    conn: Connection, person_ids: list[int]
) -> dict[int, list[ContributorName]]:
    """`{person_id: [nom, ...]}` — les noms des membres des groupes rattachés à chacune des personnes, tels que les sources les donnent."""
    if not person_ids:
        return {}
    rows = conn.execute(
        text(f"""
            SELECT g.person_id, sc.raw_author_name, sc.raw_last_name, sc.raw_first_name
            FROM {GROUP_MEMBERS}
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
    """Issue de la complétion : personnes complétées, et personnes à prénoms pleins concurrents."""

    completed: int
    conflicting: frozenset[int]


def complete_reduced_first_names(
    conn: Connection, *, repo: PgPersonRepository
) -> FirstNameCompletion:
    """Donne à chaque personne au prénom réduit le prénom plein que les membres de ses groupes attestent seul."""
    reduced = {}
    for namesake in fetch_namesakes(conn):
        initials = first_name_initials(namesake.first_name)
        if initials is not None:
            reduced[namesake.person_id] = (namesake, initials)
    names = fetch_linked_contributor_names(conn, sorted(reduced))

    completed = 0
    conflicting: set[int] = set()
    for person_id, (namesake, initials) in reduced.items():
        attested = attested_full_first_names(namesake.last_name, initials, names.get(person_id, ()))
        if len(attested) == 1:
            (first_name,) = attested.values()
            repo.rename(person_id, namesake.last_name, first_name)
            completed += 1
        elif attested:
            conflicting.add(person_id)
    return FirstNameCompletion(completed, frozenset(conflicting))
