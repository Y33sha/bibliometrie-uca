"""Router de la session admin : ouverture, vérification et fermeture. Sert `/api/auth/*`.

Le jeton et son format appartiennent à `interfaces.api.session` ; le router le pose en cookie et l'en retire.
"""

from fastapi import APIRouter, Depends, HTTPException, Response

from application.ports.repositories.user_repository import UserRepository
from domain.users import SessionUser
from interfaces.api.deps import get_admin_user, session_user, user_repo
from interfaces.api.models import AuthCheckResponse, LoginRequest, OkResponse
from interfaces.api.rate_limit import login_rate_limit
from interfaces.api.session import (
    SESSION_MAX_AGE,
    check_password,
    check_username,
    issue_token,
    session_cookie_secure,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=OkResponse)
def auth_login(
    data: LoginRequest,
    response: Response,
    _rate_limit: None = Depends(login_rate_limit),
    users: UserRepository = Depends(user_repo),
) -> OkResponse:
    """Authentifie l'admin et pose un cookie de session signé.

    Renvoie 401 si les identifiants ne correspondent pas à ceux configurés côté serveur (`ADMIN_USER` et `ADMIN_HASH`) ou si `ADMIN_USER` est absent de `ops.users`, 429 au-delà du plafond de tentatives par IP (`login_rate_limit`). Sur succès, un cookie `session` (httponly, samesite=strict, durée `SESSION_MAX_AGE`) est posé et autorise les écritures, que le middleware garde.
    """
    # Les deux confrontations s'évaluent quel que soit le sort de la première : la vérification du mot de passe coûte quelques centaines de millisecondes, la comparaison du nom une fraction de microseconde, et un refus immédiat désignerait un nom inconnu.
    nom_correspond = check_username(data.username)
    mot_de_passe_correspond = check_password(data.password)
    if not (nom_correspond and mot_de_passe_correspond):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    if users.roles_of(get_admin_user()) is None:
        raise HTTPException(status_code=401, detail="Utilisateur non autorisé")
    response.set_cookie(
        key="session",
        value=issue_token(get_admin_user()),
        httponly=True,
        secure=session_cookie_secure(),
        samesite="strict",
        max_age=SESSION_MAX_AGE,
        path="/",
    )
    return OkResponse()


@router.get("/check", response_model=AuthCheckResponse)
def auth_check(user: SessionUser | None = Depends(session_user)) -> AuthCheckResponse:
    """État de la session en cours : validité, utilisateur et rôles.

    Répond toujours 200 : le frontend s'en sert pour choisir entre le bouton de connexion et celui de déconnexion.
    """
    if user is None:
        return AuthCheckResponse(authenticated=False)
    return AuthCheckResponse(authenticated=True, login=user.login, roles=sorted(user.roles))


@router.post("/logout", response_model=OkResponse)
def auth_logout(response: Response) -> OkResponse:
    """Supprime le cookie de session (déconnexion côté client)."""
    response.delete_cookie(key="session", path="/")
    return OkResponse()
