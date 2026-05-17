"""Modèles Pydantic pour l'authentification."""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthCheckResponse(BaseModel):
    authenticated: bool
