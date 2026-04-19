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
from interfaces.api.models import LoginRequest

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/auth/login")
async def auth_login(data: LoginRequest, response: Response) -> Any:
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


@router.get("/api/auth/check")
async def auth_check(session: str | None = Cookie(None, alias="session")) -> Any:
    if session and _verify_token(session):
        return {"authenticated": True}
    return {"authenticated": False}


@router.post("/api/auth/logout")
async def auth_logout(response: Response) -> Any:
    response.delete_cookie(key="session", path="/")
    return {"ok": True}
