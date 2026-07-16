"""Router /api/auth/* — ouverture, vérification et fermeture de la session admin."""

import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from interfaces.api.deps import (
    SESSION_MAX_AGE,
    _check_password,
    _sign_token,
    _verify_token,
    get_admin_user,
)
from interfaces.api.models import AuthCheckResponse, LoginRequest, OkResponse

router = APIRouter()


@router.post("/api/auth/login", response_model=OkResponse)
def auth_login(
    data: LoginRequest,
    response: Response,
    admin_user: str = Depends(get_admin_user),
) -> OkResponse:
    """Authentifie l'admin et pose un cookie de session signé.

    Renvoie 401 si les identifiants ne correspondent pas à ceux configurés côté serveur (`ADMIN_USER` et `ADMIN_HASH`). Sur succès, un cookie `session` (httponly, samesite=strict, durée `SESSION_MAX_AGE`) est posé et autorise les écritures, que le middleware garde.
    """
    if data.username != admin_user or not _check_password(data.password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    payload = f"{admin_user}|{int(time.time())}"
    token = _sign_token(payload)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return OkResponse()


@router.get("/api/auth/check", response_model=AuthCheckResponse)
def auth_check(session: str | None = Cookie(None, alias="session")) -> AuthCheckResponse:
    """Indique si le cookie de session en cours est valide.

    Répond toujours 200 : le frontend s'en sert pour choisir entre le bouton de connexion et celui de déconnexion.
    """
    return AuthCheckResponse(authenticated=bool(session and _verify_token(session)))


@router.post("/api/auth/logout", response_model=OkResponse)
def auth_logout(response: Response) -> OkResponse:
    """Supprime le cookie de session (déconnexion côté client)."""
    response.delete_cookie(key="session", path="/")
    return OkResponse()
