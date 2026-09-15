"""Complétion des prénoms réduits à des initiales, d'après les signatures des personnes.

Une personne créée depuis une signature « Tnourji, A. » porte le prénom « A. ». Quand ses signatures lui donnent un seul prénom plein compatible (« Abdellah »), elle prend ce prénom : le rattachement par initiales compatibles ne lui envoie ensuite que les signatures de ce prénom. Quand elles lui en donnent plusieurs, elle garde ses initiales et ne reçoit aucun prénom plein de plus (`Namesake.conflicting`).
"""

from typing import NamedTuple

from sqlalchemy import Connection

from application.ports.pipeline.persons.matching import PersonsMatchingQueries
from application.ports.repositories.person_repository import PersonRepository
from application.services.persons.core import update_name
from domain.persons.matching import attested_full_first_names
from domain.persons.name_matching import first_name_initials


class FirstNameCompletion(NamedTuple):
    """Issue de la complétion : personnes complétées, et personnes à prénoms pleins concurrents."""

    completed: int
    conflicting: frozenset[int]


def complete_reduced_first_names(
    conn: Connection, queries: PersonsMatchingQueries, *, person_repo: PersonRepository
) -> FirstNameCompletion:
    """Donne à chaque personne au prénom réduit le prénom plein que ses signatures attestent seul."""
    reduced = {}
    for namesake in queries.fetch_namesakes(conn):
        initials = first_name_initials(namesake.first_name)
        if initials is not None:
            reduced[namesake.person_id] = (namesake, initials)
    names = queries.fetch_linked_signature_names(conn, sorted(reduced))

    completed = 0
    conflicting: set[int] = set()
    for person_id, (namesake, initials) in reduced.items():
        attested = attested_full_first_names(namesake.last_name, initials, names.get(person_id, ()))
        if len(attested) == 1:
            (first_name,) = attested.values()
            update_name(person_id, namesake.last_name, first_name, repo=person_repo)
            completed += 1
        elif attested:
            conflicting.add(person_id)
    return FirstNameCompletion(completed, frozenset(conflicting))
