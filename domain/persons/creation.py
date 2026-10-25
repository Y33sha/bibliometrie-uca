"""Règles de politique de création de personnes."""

from collections.abc import Sequence

from domain.publications.contribution_roles import THESIS_JURY_ROLES


def allow_person_creation(roles: Sequence[str]) -> bool:
    """Indique si la décision d'un groupe peut créer une personne pour cette contribution source, à défaut d'avoir trouvé un match.

    Le matching à une personne existante reste toujours autorisé. Une contribution source dont tous les rôles sont des rôles de jury de thèse (direction, rapport, jury, présidence) ne crée pas de personne : ces personnes entrent dans `persons` par leurs propres publications. theses.fr et ScanR donnent ces rôles.
    """
    return not roles or not set(roles) <= THESIS_JURY_ROLES
