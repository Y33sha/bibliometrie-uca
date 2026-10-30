"""Port UserRepository : utilisateurs autorisés et leurs rôles (`ops.users`, `ops.user_roles`)."""

from collections.abc import Iterable
from typing import Protocol


class UserRepository(Protocol):
    """Lecture des rôles d'un utilisateur, création d'un utilisateur."""

    def roles_of(self, login: str) -> frozenset[str] | None:
        """Renvoie les rôles de l'utilisateur `login`, ou `None` s'il est absent de `ops.users`."""
        ...

    def ensure_user(self, login: str, roles: Iterable[str]) -> None:
        """Crée l'utilisateur s'il manque et ajoute les rôles donnés à ses rôles existants."""
        ...
