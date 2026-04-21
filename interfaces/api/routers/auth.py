"""Auth endpoints: login, check, logout."""

import logging
import time
from typing import Any

from fastapi import APIRouter, Cookie, Response

from infrastructure.settings import settings
from interfaces.api.deps import (
    SESSION_MAX_AGE,
    _check_password,
    _sign_token,
    _verify_token,
)
from interfaces.api.models import AuthCheckResponse, LoginRequest, OkResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/auth/login", response_model=OkResponse)
async def auth_login(data: LoginRequest, response: Response) -> Any:
    """Authentifie l'admin et pose un cookie de session signé.

    Renvoie 401 si les identifiants ne correspondent pas à ceux
    configurés (`ADMIN_USER` / `ADMIN_PASSWORD_HASH` côté serveur).
    Sur succès, un cookie `session` (httponly, samesite=strict,
    durée `SESSION_MAX_AGE`) est posé et autorise toutes les
    mutations POST/PUT/PATCH/DELETE.
    """
    from fastapi import HTTPException

    if data.username != settings.admin_user or not _check_password(data.password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    payload = f"{settings.admin_user}|{int(time.time())}"
    token = _sign_token(payload)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return {"ok": True}


@router.get("/api/auth/check", response_model=AuthCheckResponse)
async def auth_check(session: str | None = Cookie(None, alias="session")) -> Any:
    """Indique si le cookie de session en cours est valide et non expiré.

    Ne renvoie jamais 401 — c'est un endpoint de diagnostic pour le
    frontend, qui s'en sert pour afficher le bouton login/logout.
    """
    if session and _verify_token(session):
        return {"authenticated": True}
    return {"authenticated": False}


@router.post("/api/auth/logout", response_model=OkResponse)
async def auth_logout(response: Response) -> Any:
    """Supprime le cookie de session (déconnexion côté client)."""
    response.delete_cookie(key="session", path="/")
    return {"ok": True}
