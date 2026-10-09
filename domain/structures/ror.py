"""Organisations du Research Organization Registry (ROR), référentiel externe des structures.

Le ROR décrit les organisations de recherche du monde entier et leurs relations parent/enfant. `structures.ror_id` relie le référentiel interne à ce référentiel.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from domain.errors import ValidationError
from domain.structures.identifiers import RorId

_COUNTRY_CODE = re.compile(r"^[a-z]{2}$")


class RorStatus(StrEnum):
    """Statut d'une organisation dans le ROR. Une organisation `withdrawn` est un doublon ou une erreur retirée du registre."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    WITHDRAWN = "withdrawn"


class RorType(StrEnum):
    """Type d'une organisation dans le ROR. `facility` désigne notamment les laboratoires et unités de recherche."""

    ARCHIVE = "archive"
    COMPANY = "company"
    EDUCATION = "education"
    FACILITY = "facility"
    FUNDER = "funder"
    GOVERNMENT = "government"
    HEALTHCARE = "healthcare"
    NONPROFIT = "nonprofit"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RorOrganization:
    """Organisation du ROR. `country_code` est le code ISO 3166-1 en minuscules de la première localisation."""

    ror_id: RorId
    name: str
    country_code: str
    types: frozenset[RorType]
    status: RorStatus
    parent_ids: frozenset[RorId]
    child_ids: frozenset[RorId]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValidationError(f"Organisation ROR sans nom : {self.ror_id}")
        if not _COUNTRY_CODE.match(self.country_code):
            raise ValidationError(
                f"Code pays invalide pour l'organisation ROR {self.ror_id} : {self.country_code!r}"
            )


def ror_relations(organizations: list[RorOrganization]) -> frozenset[tuple[RorId, RorId]]:
    """Couples `(parent, enfant)` déclarés par l'une ou l'autre des deux organisations, limités aux organisations de la liste.

    Le ROR déclare chaque relation des deux côtés, à quelques exceptions près : l'union les couvre.
    """
    known = {org.ror_id for org in organizations}
    pairs = {(parent, org.ror_id) for org in organizations for parent in org.parent_ids} | {
        (org.ror_id, child) for org in organizations for child in org.child_ids
    }
    return frozenset(
        (parent, child)
        for parent, child in pairs
        if parent != child and parent in known and child in known
    )
