"""Condition de création d'une personne depuis une contribution source."""

from collections.abc import Sequence

from domain.contributions.contribution_roles import THESIS_JURY_ROLES, ContributionRole

_ROLES_WITHOUT_CREATION = THESIS_JURY_ROLES | {ContributionRole.INVENTOR}
"""Rôles sans création de personne : jury de thèse, inventeur. Ces personnes entrent dans `persons` par leurs propres publications."""


def allow_person_creation(roles: Sequence[str]) -> bool:
    """Vrai si la contribution source peut fonder une personne, faute de personne existante. Faux si tous ses rôles sont dans `_ROLES_WITHOUT_CREATION`."""
    return not roles or not set(roles) <= _ROLES_WITHOUT_CREATION
