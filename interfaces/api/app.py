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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from application import audit
from domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from infrastructure.log import configure_root_logging
from interfaces.api.deps import _get_pool, _verify_token, get_cursor

# Configure le root logger (format JSON par défaut, texte si LOG_FORMAT=text).
# À faire AVANT l'import des routers qui peuvent créer leur propre logger.
configure_root_logging()

from interfaces.api.routers import (  # noqa: E402
    addresses,
    admin_duplicates,
    admin_feedback,
    admin_person_duplicates,
    admin_pipeline,
    auth,
    authorships,
    config,
    docs,
    hal_problems,
    journals,
    laboratories,
    perimeters,
    persons,
    publications,
    publishers,
    stats,
    structures,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Bibliométrie UCA")


# ----- Exception handlers -----
#
# Les services lèvent des exceptions métier (domain.errors) sans connaître HTTP.
# Ces handlers sont le SEUL endroit qui traduit une erreur métier en code HTTP.


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> Any:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError) -> Any:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> Any:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(UnauthorizedError)
async def unauthorized_handler(request: Request, exc: UnauthorizedError) -> Any:
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> Any:
    # Filet de sécurité pour une DomainError non spécialisée ci-dessus.
    logger.warning("DomainError non mappée : %s", exc)
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> Any:
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
async def auth_middleware(request: Request, call_next: Any) -> Any:
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


@app.middleware("http")
async def strip_prefix(request: Request, call_next: Any) -> Any:
    """Strip /bibliometrie prefix pour que les routes /api/* fonctionnent en accès direct."""
    if request.url.path.startswith("/bibliometrie/api/"):
        request.scope["path"] = request.url.path[len("/bibliometrie") :]
    return await call_next(request)


# Endpoints exclus du logging de timing (trop bavards, peu utiles)
_METRICS_SKIP_PATHS = ("/api/health", "/api/metrics")


@app.middleware("http")
async def timing_middleware(request: Request, call_next: Any) -> Any:
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


@app.get("/api/health")
async def health() -> Any:
    """Vérifie que l'API est opérationnelle, la DB accessible, et la fraîcheur
    des données (date de la dernière extraction par source).
    """
    sandbox = os.environ.get("BIBLIOMETRIE_SANDBOX") == "1"
    try:
        with get_cursor() as (cur, conn):
            cur.execute("SELECT 1")
            cur.execute(
                "SELECT source, MAX(created_at) AS last_at FROM source_publications GROUP BY source"
            )
            rows = cur.fetchall()
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "db": str(e)})

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=_STALE_THRESHOLD_DAYS)
    last_extraction: dict = {}
    stale: list[str] = []
    for r in rows:
        source = r["source"]
        last_at = r["last_at"]
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
        "sandbox": sandbox,
        "pipeline_running": _PIPELINE_STATUS_FILE.exists(),
        "last_extraction": last_extraction,
        "stale_sources": stale,
        "stale_threshold_days": _STALE_THRESHOLD_DAYS,
    }


# ----- Metrics -----


@app.get("/api/metrics")
async def metrics() -> Any:
    """Métriques internes : état du pool de connexions DB.

    Le timing des requêtes est émis via le middleware `timing_middleware`
    (champs `method`, `path`, `status`, `duration_ms` en JSON structuré).
    """
    pool = _get_pool()
    stats = pool.get_stats()
    pool_size = stats.get("pool_size", 0)
    available = stats.get("pool_available", 0)
    return {
        "db_pool": {
            "minconn": pool.min_size,
            "maxconn": pool.max_size,
            "in_use": pool_size - available,
            "available": available,
        },
    }


# ----- Root redirect -----


@app.get("/")
async def root() -> Any:
    return RedirectResponse("/bibliometrie/stats")


# ----- Include routers -----

app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(publications.router)
app.include_router(admin_duplicates.router)
app.include_router(addresses.router)
app.include_router(admin_feedback.router)
app.include_router(laboratories.router)
app.include_router(structures.router)
app.include_router(authorships.router)
app.include_router(persons.router)
app.include_router(admin_person_duplicates.router)
app.include_router(hal_problems.router)
app.include_router(docs.router)
app.include_router(config.router)
app.include_router(perimeters.router)
app.include_router(publishers.router)
app.include_router(journals.router)
app.include_router(admin_pipeline.router)


if __name__ == "__main__":
    import uvicorn

    print("Démarrage du serveur sur http://localhost:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003)
