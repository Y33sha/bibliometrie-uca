"""Shared dependencies: SPA static files, auth helpers, sync DB factories.

Les factories DB sync (`db_conn_sync`) sont utilisées par les routers
migrés en `def` (chantier `docs/chantiers/sync-async-deduplication.md`,
option D). Pendant la migration progressive, elles cohabitent avec les
factories async dans `interfaces/api/async_deps.py`. Phase 3 du
chantier supprimera la moitié async une fois tous les routers basculés.
"""

import hashlib
import hmac
import os
import time
from collections.abc import Iterator
from typing import Any

import bcrypt
from fastapi import Cookie, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Connection

from application.ports.config import ConfigStore
from application.ports.config_queries import ConfigQueries
from application.ports.subjects_queries import SubjectsAdminQueries
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queries.config import PgConfig, PgConfigQueries
from infrastructure.db.queries.subjects import PgSubjectsAdminQueries
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


# ----- Sync DB factories (chantier sync-async-deduplication option D) -----


def db_conn_sync() -> Iterator[Connection]:
    """Connection SA sync ouverte en transaction, pour les routers `def`.

    À utiliser via `Depends(db_conn_sync)`. Ouvre `engine.begin()` :
    commit auto en sortie sans exception, rollback sinon — équivalent
    sync de `db_conn` côté async (`interfaces/api/async_deps.py`).

    Toute dépendance qui en dérive (`*_repo` sync, query adapters
    sync) doit partager la même connexion → même transaction.
    """
    engine = get_sync_engine()
    with engine.begin() as conn:
        yield conn


def subjects_admin_queries(
    conn: Connection = Depends(db_conn_sync),
) -> SubjectsAdminQueries:
    return PgSubjectsAdminQueries(conn)


def config_queries_sync(conn: Connection = Depends(db_conn_sync)) -> ConfigQueries:
    return PgConfigQueries(conn)


def config_store_sync(conn: Connection = Depends(db_conn_sync)) -> ConfigStore:
    return PgConfig(conn)
