"""Modèles Pydantic pour l'authentification."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthCheckResponse(BaseModel):
    """Résultat de la vérification de session : `authenticated` dit si la requête porte une session valide."""

    authenticated: bool
