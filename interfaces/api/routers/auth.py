"""Router de la session admin : ouverture, vérification et fermeture. Sert `/api/auth/*`.

Le jeton et son format appartiennent à `interfaces.api.session` ; le router le pose en cookie et l'en retire.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from interfaces.api.deps import get_admin_user
from interfaces.api.models import AuthCheckResponse, LoginRequest, OkResponse
from interfaces.api.session import SESSION_MAX_AGE, check_password, issue_token, read_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=OkResponse)
def auth_login(
    data: LoginRequest,
    response: Response,
    admin_user: str = Depends(get_admin_user),
) -> OkResponse:
    """Authentifie l'admin et pose un cookie de session signé.

    Renvoie 401 si les identifiants ne correspondent pas à ceux configurés côté serveur (`ADMIN_USER` et `ADMIN_HASH`). Sur succès, un cookie `session` (httponly, samesite=strict, durée `SESSION_MAX_AGE`) est posé et autorise les écritures, que le middleware garde.
    """
    if data.username != admin_user or not check_password(data.password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    response.set_cookie(
        key="session",
        value=issue_token(admin_user),
        httponly=True,
        samesite="strict",
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return OkResponse()


@router.get("/check", response_model=AuthCheckResponse)
def auth_check(session: str | None = Cookie(None, alias="session")) -> AuthCheckResponse:
    """Indique si le cookie de session en cours est valide.

    Répond toujours 200 : le frontend s'en sert pour choisir entre le bouton de connexion et celui de déconnexion.
    """
    return AuthCheckResponse(authenticated=bool(session and read_session(session)))


@router.post("/logout", response_model=OkResponse)
def auth_logout(response: Response) -> OkResponse:
    """Supprime le cookie de session (déconnexion côté client)."""
    response.delete_cookie(key="session", path="/")
    return OkResponse()
