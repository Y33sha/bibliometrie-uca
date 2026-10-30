"""Modèles Pydantic pour l'authentification."""

from application.ports.model import Model


class LoginRequest(Model):
    username: str
    password: str


class AuthCheckResponse(Model):
    """État de la session et, si elle est valide, son utilisateur."""

    authenticated: bool
    """Vrai si la requête a une session valide."""
    login: str | None = None
    roles: list[str] = []
