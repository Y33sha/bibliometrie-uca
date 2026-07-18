"""Bibliométrie UCA — application FastAPI : point d'assemblage de la surface HTTP.

Câble le cycle de vie de l'engine SQLAlchemy, la traduction des erreurs métier en codes HTTP, les middlewares (authentification des écritures, mesure de durée), les routers, et le service du frontend buildé.

Lancement en développement : `bash start.sh`, qui démarre uvicorn sur le port 8003 et le serveur de développement du frontend.
"""

import logging
import os
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from application import audit_log
from domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PublisherMergeBlockedError,
    RejectedPairError,
    UnauthorizedError,
    ValidationError,
)
from infrastructure.db.engine import build_sync_engine, set_sync_engine
from infrastructure.observability.log import configure_root_logging
from interfaces.api.models.errors import (
    PublisherMergeBlockedResponse,
    RejectedPairsResponse,
)
from interfaces.api.session import read_session
from interfaces.api.spa import BUILD_DIR, SPAStaticFiles

# Configure le root logger (format JSON par défaut, texte si LOG_FORMAT=text).
# À faire AVANT l'import des routers qui peuvent créer leur propre logger.
configure_root_logging()

from interfaces.api.routers import (  # noqa: E402
    addresses,
    auth,
    authorships,
    config,
    countries,
    feedback,
    hal_problems,
    journals,
    laboratories,
    name_forms,
    perimeters,
    persons,
    pipeline,
    publications,
    publishers,
    stats,
    structures,
    subjects,
)

logger = logging.getLogger(__name__)


# ----- Lifespan -----
#
# Construit l'engine SQLAlchemy au démarrage et le libère à l'arrêt.
# Les routes le consomment via `db_conn`.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    sync_engine = build_sync_engine()
    set_sync_engine(sync_engine)
    try:
        yield
    finally:
        sync_engine.dispose()
        set_sync_engine(None)


# `root_path` : préfixe de déploiement (par exemple `/bibliometrie` en production).
# Le serveur ASGI retire ce préfixe (uvicorn `--root-path` ou variable
# d'environnement `UVICORN_ROOT_PATH`) avant que FastAPI route ; la valeur sert ici
# à générer les URLs absolues d'OpenAPI et les redirections. Vide par défaut : en
# développement local, ou derrière un reverse proxy qui le retire en amont.
app = FastAPI(
    title="Bibliométrie UCA",
    lifespan=lifespan,
    root_path=os.environ.get("ROOT_PATH", ""),
)


# ----- Exception handlers -----
#
# Les services lèvent des exceptions métier (domain.errors) sans connaître HTTP.
# Ces handlers font le mapping erreur → statut + corps à l'exécution. Le contrat
# (quel statut, quel corps) se déclare, lui, sur la route via `responses={}` :
# les erreurs à corps trivial se contentent de `{detail}`, les deux à corps
# structuré passent par un modèle publié (`interfaces/api/models/errors.py`).


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(PublisherMergeBlockedError)
async def publisher_merge_blocked_handler(
    request: Request, exc: PublisherMergeBlockedError
) -> JSONResponse:
    body = PublisherMergeBlockedResponse.model_validate(
        {"detail": str(exc), "blocking_journals": exc.blocking_journals}
    )
    return JSONResponse(status_code=409, content=body.model_dump())


@app.exception_handler(RejectedPairError)
async def rejected_pair_handler(request: Request, exc: RejectedPairError) -> JSONResponse:
    body = RejectedPairsResponse.model_validate(
        {"detail": str(exc), "rejected_pairs": exc.rejected_pairs}
    )
    return JSONResponse(status_code=409, content=body.model_dump())


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
    """Protège les endpoints d'écriture (POST/PUT/DELETE/PATCH), hors authentification.

    Journalise les actions admin réussies (statut < 400) sous le record structuré `admin_action`, qui porte l'utilisateur, la méthode, le chemin et le statut.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return await call_next(request)

    path = request.scope["path"]
    if path.startswith("/api/auth/"):
        return await call_next(request)

    token = request.cookies.get("session")
    admin_user = read_session(token) if token else None
    if not admin_user:
        return JSONResponse(status_code=401, content={"detail": "Non authentifié"})

    # Propager l'utilisateur dans le contexte async pour que emit_event()
    # l'inclue dans les enregistrements audit_log, sans polluer les
    # signatures des services métier.
    token_ctx = audit_log.set_current_user(admin_user)
    try:
        response = await call_next(request)
    finally:
        audit_log.reset_current_user(token_ctx)

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
async def timing_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Mesure la durée de chaque requête, pose l'en-tête `X-Response-Time` et journalise un record structuré `request_completed`."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Response-Time"] = f"{duration_ms}ms"

    logger.info(
        "request_completed",
        extra={
            "method": request.method,
            "path": request.scope.get("path", ""),
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


# ----- Include routers -----

app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(publications.router)
app.include_router(addresses.router)
app.include_router(countries.router)
app.include_router(feedback.router)
app.include_router(laboratories.router)
app.include_router(structures.router)
app.include_router(name_forms.router)
app.include_router(persons.router)
app.include_router(authorships.router)
app.include_router(hal_problems.router)
app.include_router(config.router)
app.include_router(perimeters.router)
app.include_router(publishers.router)
app.include_router(journals.router)
app.include_router(pipeline.router)
app.include_router(subjects.router)


# ----- Frontend SPA (prod) -----
#
# En prod, le frontend buildé (adapter-static) est servi par FastAPI : la SPA
# (ssr=false) et les docs prérendues vivent dans interfaces/frontend/build.
# Monté en dernier — catch-all — pour que les routes /api/* matchent d'abord.
# Absent en dev (vite sert le frontend) : on ne monte que si le build existe.
if BUILD_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=BUILD_DIR, html=True), name="spa")
