"""Modèles Pydantic pour l'authentification."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthCheckResponse(BaseModel):
    """État de la session et, si elle est valide, son utilisateur."""

    authenticated: bool
    """Vrai si la requête a une session valide."""
    login: str | None = None
    roles: list[str] = []
