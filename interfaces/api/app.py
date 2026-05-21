"""
Bibliométrie UCA — API FastAPI.

Usage:
    cd publisher-stats
    python webapp/app.py

Puis ouvrir http://localhost:8003
"""

import logging
import os
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.pool import QueuePool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from application import audit
from domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from domain.types import JsonValue
from infrastructure.db.engine import (
    build_sync_engine,
    get_sync_engine,
    set_sync_engine,
)
from infrastructure.observability.log import configure_root_logging
from interfaces.api.deps import _verify_token

# Configure le root logger (format JSON par défaut, texte si LOG_FORMAT=text).
# À faire AVANT l'import des routers qui peuvent créer leur propre logger.
configure_root_logging()

from interfaces.api.routers import (  # noqa: E402
    auth,
    docs,
    hal_problems,
    journals,
    laboratories,
    persons,
    publications,
    publishers,
    stats,
    subjects,
)
from interfaces.api.routers.admin import addresses as admin_addresses  # noqa: E402
from interfaces.api.routers.admin import (  # noqa: E402
    authorships as admin_authorships,
)
from interfaces.api.routers.admin import feedback as admin_feedback  # noqa: E402
from interfaces.api.routers.admin import (  # noqa: E402
    perimeters as admin_perimeters,
)
from interfaces.api.routers.admin import (  # noqa: E402
    person_duplicates as admin_person_duplicates,
)
from interfaces.api.routers.admin import persons as admin_persons  # noqa: E402
from interfaces.api.routers.admin import (  # noqa: E402
    pipeline_config as admin_pipeline_config,
)
from interfaces.api.routers.admin import (  # noqa: E402
    pipeline_logs as admin_pipeline_logs,
)
from interfaces.api.routers.admin import (  # noqa: E402
    publication_duplicates as admin_publication_duplicates,
)
from interfaces.api.routers.admin import (  # noqa: E402
    structures as admin_structures,
)

logger = logging.getLogger(__name__)


# ----- Lifespan -----
#
# Initialise/dispose l'Engine SA sync pour toute la surface API.
# Les routers `def` consomment cet engine via `db_conn_sync`.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    sync_engine = build_sync_engine()
    set_sync_engine(sync_engine)
    try:
        yield
    finally:
        sync_engine.dispose()
        set_sync_engine(None)


# `root_path` : préfixe de déploiement (ex. `/bibliometrie` en prod).
# Le strip du préfixe est fait par le serveur ASGI (uvicorn `--root-path` ou
# env `UVICORN_ROOT_PATH`) avant que FastAPI route ; cette valeur sert ici à
# générer correctement les URLs absolues dans OpenAPI et les redirections.
# Vide par défaut (dev local nu, ou reverse proxy qui strip déjà en amont).
app = FastAPI(
    title="Bibliométrie UCA",
    lifespan=lifespan,
    root_path=os.environ.get("ROOT_PATH", ""),
)


# ----- Exception handlers -----
#
# Les services lèvent des exceptions métier (domain.errors) sans connaître HTTP.
# Ces handlers sont le SEUL endroit qui traduit une erreur métier en code HTTP.


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(UnauthorizedError)
async def unauthorized_handler(request: Request, exc: UnauthorizedError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    # Filet de sécurité pour une DomainError non spécialisée ci-dessus.
    logger.warning("DomainError non mappée : %s", exc)
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Renvoie du JSON 500 au lieu de HTML pour les erreurs non gérées."""
    logger.error(
        "Erreur non gérée sur %s %s\n%s", request.method, request.url.path, traceback.format_exc()
    )
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})


# ----- CORS -----
# CORS_ORIGINS est obligatoire (défini dans .env en dev, injecté en prod).
_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Middleware -----


@app.middleware("http")
async def auth_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Protège les endpoints d'écriture (POST/PUT/DELETE/PATCH) sauf auth.

    Log aussi les actions admin réussies (status < 400) pour traçabilité —
    format key=value parseable : `admin_action user=admin method=POST
    path=/api/... status=200`.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return await call_next(request)

    path = request.scope["path"]
    if path.startswith("/api/auth/"):
        return await call_next(request)

    token = request.cookies.get("session")
    payload = _verify_token(token) if token else None
    if not payload:
        return JSONResponse(status_code=401, content={"detail": "Non authentifié"})

    # Payload format : "admin_user|timestamp"
    admin_user = payload.split("|", 1)[0] if "|" in payload else payload

    # Propager l'utilisateur dans le contexte async pour que emit_event()
    # l'inclue dans les enregistrements audit_log, sans polluer les
    # signatures des services métier.
    token_ctx = audit.set_current_user(admin_user)
    try:
        response = await call_next(request)
    finally:
        audit.reset_current_user(token_ctx)

    if response.status_code < 400:
        logger.info(
            "admin_action",
            extra={
                "user": admin_user,
                "method": request.method,
                "path": path,
                "status": response.status_code,
            },
        )
    return response


# Endpoints exclus du logging de timing (trop bavards, peu utiles)
_METRICS_SKIP_PATHS = ("/api/health", "/api/metrics")


@app.middleware("http")
async def timing_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Mesure la durée de chaque requête, ajoute un header X-Response-Time
    et log un record `request_completed` structuré (sauf /api/health et /api/metrics).
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Response-Time"] = f"{duration_ms}ms"

    path = request.scope.get("path", "")
    if not any(path.startswith(p) for p in _METRICS_SKIP_PATHS):
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
    return response


# ----- Health check -----

# Seuil à partir duquel une source est considérée "stale" (pas extraite
# récemment). theses.fr est mensuel, les autres devraient être hebdomadaires.
_STALE_THRESHOLD_DAYS = 7
_PIPELINE_STATUS_FILE = Path(__file__).resolve().parent.parent.parent / "logs" / "status.json"


@app.get("/api/health", response_model=None)
def health() -> JSONResponse | dict[str, JsonValue]:
    """Vérifie que l'API est opérationnelle, la DB accessible, et la fraîcheur
    des données (date de la dernière extraction par source).
    """
    try:
        engine = get_sync_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            rows = conn.execute(
                text(
                    "SELECT source, MAX(created_at) AS last_at "
                    "FROM source_publications GROUP BY source"
                )
            ).all()
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "db": str(e)})

    now = datetime.now(UTC)
    threshold = now - timedelta(days=_STALE_THRESHOLD_DAYS)
    last_extraction: dict[str, dict[str, JsonValue]] = {}
    stale: list[str] = []
    for r in rows:
        source = r.source
        last_at = r.last_at
        is_stale = bool(last_at and last_at < threshold)
        last_extraction[source] = {
            "at": last_at.isoformat() if last_at else None,
            "age_days": (now - last_at).days if last_at else None,
            "stale": is_stale,
        }
        if is_stale:
            stale.append(source)

    return {
        "status": "ok",
        "db": "ok",
        "pipeline_running": _PIPELINE_STATUS_FILE.exists(),
        "last_extraction": last_extraction,
        "stale_sources": stale,
        "stale_threshold_days": _STALE_THRESHOLD_DAYS,
    }


# ----- Metrics -----


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    """Métriques internes : état du pool de connexions SQLAlchemy.

    Le timing des requêtes est émis via le middleware `timing_middleware`
    (champs `method`, `path`, `status`, `duration_ms` en JSON structuré).
    """
    engine = get_sync_engine()
    # `engine.pool` est typé `Pool` (interface mince), mais l'instance
    # concrète est un `QueuePool` qui expose size/checkedout/checkedin.
    pool = cast(QueuePool, engine.pool)
    size = pool.size()
    return {
        "db_pool": {
            "minconn": size,
            "maxconn": size + pool._max_overflow,
            "in_use": pool.checkedout(),
            "available": pool.checkedin(),
        },
    }


# ----- Root redirect -----


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/bibliometrie/stats")


# ----- Include routers -----

app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(publications.router)
app.include_router(admin_publication_duplicates.router)
app.include_router(admin_addresses.router)
app.include_router(admin_feedback.router)
app.include_router(laboratories.router)
app.include_router(admin_structures.router)
app.include_router(persons.router)
app.include_router(admin_persons.router)
app.include_router(admin_authorships.router)
app.include_router(admin_person_duplicates.router)
app.include_router(hal_problems.router)
app.include_router(docs.router)
app.include_router(admin_pipeline_config.router)
app.include_router(admin_perimeters.router)
app.include_router(publishers.router)
app.include_router(journals.router)
app.include_router(admin_pipeline_logs.router)
app.include_router(subjects.router)


if __name__ == "__main__":
    import uvicorn

    print("Démarrage du serveur sur http://localhost:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003)
