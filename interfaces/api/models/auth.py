"""Modèles Pydantic pour l'authentification."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthCheckResponse(BaseModel):
    """État de la session : `authenticated` dit si la requête a une session valide, `login` et `roles` désignent son utilisateur."""

    authenticated: bool
    login: str | None = None
    roles: list[str] = []
