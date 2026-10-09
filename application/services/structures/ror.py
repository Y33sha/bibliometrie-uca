"""Chargement du référentiel ROR depuis son dump."""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import Connection

from application.ports.repositories.ror_repository import RorRepository
from domain.structures.ror import RorOrganization, ror_relations


@dataclass(frozen=True, slots=True)
class RorImportStats:
    organizations: int
    relations: int


def import_ror_dump(
    conn: Connection,
    organizations: Iterable[RorOrganization],
    *,
    repo: RorRepository,
) -> RorImportStats:
    """Remplit le référentiel ROR avec les organisations du dump et leurs relations parent/enfant, en une transaction."""
    orgs = list(organizations)
    relations = ror_relations(orgs)
    repo.replace_all(orgs, relations)
    conn.commit()
    return RorImportStats(organizations=len(orgs), relations=len(relations))
