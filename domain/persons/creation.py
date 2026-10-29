"""Condition de création d'une personne depuis une contribution source."""

from collections.abc import Sequence

from domain.publications.contribution_roles import THESIS_JURY_ROLES


def allow_person_creation(roles: Sequence[str]) -> bool:
    """Vrai si la contribution source peut fonder une personne, faute de personne existante. Faux si tous ses rôles sont des rôles de jury de thèse : ces personnes entrent dans `persons` par leurs propres publications."""
    return not roles or not set(roles) <= THESIS_JURY_ROLES
