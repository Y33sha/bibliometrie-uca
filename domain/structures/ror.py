"""Organisations du Research Organization Registry (ROR), référentiel externe des structures.

Le ROR décrit les organisations de recherche du monde entier et leurs relations parent/enfant. `structures.ror_id` relie le référentiel interne à ce référentiel.
"""

from dataclasses import dataclass
from enum import StrEnum


class RorStatus(StrEnum):
    """Statut d'une organisation dans le ROR. Une organisation `withdrawn` est un doublon ou une erreur retirée du registre."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True)
class RorOrganization:
    """Organisation du ROR. `country_code` est le code ISO en minuscules de la première localisation."""

    ror_id: str
    name: str
    country_code: str | None
    types: tuple[str, ...]
    status: RorStatus
    parent_ids: tuple[str, ...]
    child_ids: tuple[str, ...]
