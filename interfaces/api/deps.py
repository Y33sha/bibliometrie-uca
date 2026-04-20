"""Shared dependencies: DB connection, auth helpers."""

import hashlib
import hmac
import os
import time
from contextlib import contextmanager
from typing import Any

import bcrypt
from fastapi import Cookie, HTTPException
from fastapi.staticfiles import StaticFiles

from infrastructure.settings import settings

# ----- SPA Static Files -----

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(PROJECT_ROOT, "interfaces", "frontend", "build")


class SPAStaticFiles(StaticFiles):
    """Sert les fichiers statiques avec fallback index.html pour le routage SPA."""

    async def get_response(self, path: Any, scope: Any) -> Any:
        try:
            return await super().get_response(path, scope)
        except Exception:
            return await super().get_response("index.html", scope)


# ----- Auth helpers -----

SESSION_MAX_AGE = 86400 * 7  # 7 jours


def _sign_token(payload: str) -> str:
    sig = hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_token(token: str) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(
        settings.session_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        parts = payload.split("|")
        ts = int(parts[1])
        if time.time() - ts > SESSION_MAX_AGE:
            return None
    except (IndexError, ValueError):
        return None
    return payload


def _check_password(password: str) -> bool:
    if not settings.admin_hash:
        return False
    return bcrypt.checkpw(password.encode(), settings.admin_hash.encode())


def require_admin(session: str | None = Cookie(None, alias="session")) -> Any:
    """Dépendance FastAPI : vérifie que l'utilisateur est authentifié."""
    if not session or not _verify_token(session):
        raise HTTPException(status_code=401, detail="Non authentifié")


# ----- DB helpers -----

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool = None


def _get_pool() -> Any:
    global _pool
    if _pool is None:
        db_args = settings.db_args
        if os.environ.get("BIBLIOMETRIE_SANDBOX") == "1":
            db_args["dbname"] = "bibliometrie_sandbox"
        _pool = ConnectionPool(
            conninfo="",
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            kwargs={**db_args, "row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def get_cursor() -> Any:
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            yield cur, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ----- Perimeter root -----

_root_structure_id: int | None = None


def get_root_structure_id() -> int:
    """Retourne l'ID de la structure racine du périmètre principal.

    Lit perimeters.structure_ids[1] pour le périmètre configuré dans
    config.perimeter_persons. Valeur cachée après le premier appel.
    """
    global _root_structure_id
    if _root_structure_id is not None:
        return _root_structure_id
    with get_cursor() as (cur, _):
        cur.execute("""
            SELECT p.structure_ids[1] AS root_id
            FROM config c
            JOIN perimeters p ON p.code = c.value #>> '{}'
            WHERE c.key = 'perimeter_persons'
        """)
        row = cur.fetchone()
        if row and row["root_id"]:
            _root_structure_id = row["root_id"]
        else:
            _root_structure_id = 0  # Périmètre non configuré — les filtres APC seront sans effet
    return _root_structure_id
