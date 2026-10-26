"""Utilisateurs de l'application et leurs rôles."""

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """Rôle d'un utilisateur. Chaque valeur a sa ligne dans `ops.roles`."""

    ADMIN = "admin"


@dataclass(frozen=True)
class SessionUser:
    """Utilisateur d'une session ouverte, avec ses rôles."""

    login: str
    roles: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return Role.ADMIN in self.roles
