"""Shared dependencies: DB connection, auth helpers."""

import os
import sys
import hashlib
import hmac
import time
from contextlib import contextmanager

from fastapi import Cookie, HTTPException
from fastapi.staticfiles import StaticFiles

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DB, DB_POOL_MIN, DB_POOL_MAX, ADMIN_USER, ADMIN_SALT, ADMIN_HASH, SESSION_SECRET


# ----- SPA Static Files -----

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(PROJECT_ROOT, "frontend", "build")


class SPAStaticFiles(StaticFiles):
    """Sert les fichiers statiques avec fallback index.html pour le routage SPA."""
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except Exception:
            return await super().get_response("index.html", scope)


# ----- Auth helpers -----

SESSION_MAX_AGE = 86400 * 7  # 7 jours


def _sign_token(payload: str) -> str:
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_token(token: str) -> str | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
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
    return hashlib.sha256((ADMIN_SALT + password).encode()).hexdigest() == ADMIN_HASH


def require_admin(session: str | None = Cookie(None, alias="session")):
    """Dépendance FastAPI : vérifie que l'utilisateur est authentifié."""
    if not session or not _verify_token(session):
        raise HTTPException(status_code=401, detail="Non authentifié")


# ----- DB helpers -----

from psycopg2.pool import ThreadedConnectionPool

_pool = ThreadedConnectionPool(minconn=DB_POOL_MIN, maxconn=DB_POOL_MAX, **DB)


@contextmanager
def get_cursor():
    conn = _pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


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
