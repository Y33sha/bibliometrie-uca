"""Auth endpoints: login, check, logout."""

import time

from fastapi import APIRouter, Response, Cookie

from backend.deps import (
    ADMIN_USER, _sign_token, _verify_token, _check_password,
    SESSION_MAX_AGE,
)
from backend.models import LoginRequest

router = APIRouter()


@router.post("/api/auth/login")
async def auth_login(data: LoginRequest, response: Response):
    from fastapi import HTTPException
    if data.username != ADMIN_USER or not _check_password(data.password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    payload = f"{ADMIN_USER}|{int(time.time())}"
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
async def auth_check(session: str | None = Cookie(None, alias="session")):
    if session and _verify_token(session):
        return {"authenticated": True}
    return {"authenticated": False}


@router.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie(key="session", path="/")
    return {"ok": True}
