"""Application FastAPI : assemblage de la surface HTTP.

Câble le cycle de vie de l'engine SQLAlchemy, la traduction des erreurs métier en codes HTTP, les middlewares, les routers et le service du frontend buildé.

Lancement en développement : `bash start.sh`.
"""

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, IntegrityError, OperationalError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from application import audit_log
from domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PublisherMergeBlockedError,
    RejectedPairError,
    ValidationError,
)
from infrastructure.db.engine import build_sync_engine, set_sync_engine
from infrastructure.db.read_only_guard import read_request
from infrastructure.observability.log import configure_root_logging
from infrastructure.settings import settings
from interfaces.api.deps import READ_ONLY_METHODS, ensure_admin_user, load_session_user
from interfaces.api.disconnect_cancellation import CancelOnDisconnect, request_cancellation
from interfaces.api.models.errors import (
    PublisherMergeBlockedResponse,
    RejectedPairsResponse,
)
from interfaces.api.params import requested_offset
from interfaces.api.rate_limit import read_allowed
from interfaces.api.route_path import RootPath, route_path
from interfaces.api.session import check_auth_config
from interfaces.api.spa import BUILD_DIR, SPAStaticFiles

# Configure le root logger avant l'import des routers, qui créent leur propre logger.
configure_root_logging()

from interfaces.api.routers import (  # noqa: E402
    addresses,
    auth,
    config,
    contributions,
    countries,
    entity_labels,
    feedback,
    hal_problems,
    monographs,
    perimeters,
    persons,
    pipeline_runs,
    publications,
    publishers,
    serials,
    sources,
    stats,
    structures,
    subjects,
)

logger = logging.getLogger(__name__)


# ----- Lifespan -----


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    check_auth_config()
    # Le limiteur est attaché à la boucle d'événements : il se règle une fois celle-ci démarrée.
    anyio.to_thread.current_default_thread_limiter().total_tokens = settings.api_threadpool_size
    sync_engine = build_sync_engine("app")
    set_sync_engine(sync_engine)
    await anyio.to_thread.run_sync(ensure_admin_user)
    try:
        yield
    finally:
        sync_engine.dispose()
        set_sync_engine(None)


# Préfixe de déploiement (`/bibliometrie` en production), vide pour un service à la racine. Cf. `route_path`.
ROOT_PATH = os.environ.get("ROOT_PATH", "")

# Docs interactives activées par `expose_api_docs`, en développement seulement : elles décrivent toute l'API, admin comprise.
_expose_docs = settings.expose_api_docs
app = FastAPI(
    title="Bibliométrie",
    lifespan=lifespan,
    docs_url="/docs" if _expose_docs else None,
    redoc_url="/redoc" if _expose_docs else None,
    openapi_url="/openapi.json" if _expose_docs else None,
)


# ----- Exception handlers -----
#
# Traduisent les exceptions métier (`domain.errors`) en statut HTTP. Chaque route déclare ses statuts d'erreur dans `responses={}` ; les corps structurés ont leur modèle dans `interfaces/api/models/errors.py`.
#
# 422 : requête bien formée que le serveur refuse (paramètre, règle du domaine, valeur non représentable en base), comme la validation native de FastAPI. 409 : conflit avec l'état courant.


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(PublisherMergeBlockedError)
async def publisher_merge_blocked_handler(
    request: Request, exc: PublisherMergeBlockedError
) -> JSONResponse:
    body = PublisherMergeBlockedResponse.model_validate(
        {"detail": str(exc), "blocking_serials": exc.blocking_serials}
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


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    # Sous-classe de DomainError sans handler dédié.
    logger.warning("DomainError non mappée : %s", exc)
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Traduit une violation de contrainte (clé étrangère, unicité, CHECK) en 409.

    Le détail SQL reste au journal : il expose la structure interne de la base.
    """
    logger.warning("Violation d'intégrité sur %s %s : %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=409,
        content={"detail": "La requête viole une contrainte d'intégrité des données."},
    )


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError) -> JSONResponse:
    """Traduit en 422 une valeur que le driver refuse d'envoyer à la base (octet NUL, par exemple), et laisse le reste en 500.

    Un refus du driver se reconnaît à l'absence de `sqlstate`, que seul le serveur renseigne. `TextParam` écarte ces valeurs des paramètres de route ; ce handler couvre les corps de requête et les paramètres déclarés sans `TextParam`. Une erreur avec `sqlstate` signale un contrôle manquant en amont : elle reste en 500.
    """
    if getattr(exc.orig, "sqlstate", None) is not None:
        raise exc
    logger.warning(
        "Valeur refusée par le driver sur %s %s : %s", request.method, request.url.path, exc.orig
    )
    return JSONResponse(
        status_code=422,
        content={"detail": "La requête porte une valeur que la base ne peut pas représenter."},
    )


# SQLSTATE d'une requête interrompue par Postgres : plafond `statement_timeout` ou annulation.
_QUERY_CANCELED = "57014"

# Statut d'une requête abandonnée par le client, d'usage chez nginx. La réponse n'atteint personne ; le statut sert au journal.
_CLIENT_CLOSED_REQUEST = 499


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError) -> Response:
    """Traduit en 503 une lecture interrompue par le plafond de durée (`api_read_statement_timeout_s`), en 499 une lecture annulée par la déconnexion du client (`CancelOnDisconnect`), et laisse le reste en 500."""
    if getattr(exc.orig, "sqlstate", None) != _QUERY_CANCELED:
        raise exc
    cancellation = request_cancellation(request)
    if cancellation is not None and cancellation.cancelled:
        return Response(status_code=_CLIENT_CLOSED_REQUEST)
    logger.warning(
        "Requête interrompue (durée maximale dépassée) sur %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "La requête a dépassé la durée maximale autorisée."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Renvoie du JSON 500 au lieu de HTML pour les erreurs non gérées."""
    logger.error("Erreur non gérée sur %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})


# ----- Middleware -----
#
# Starlette empile les middlewares dans l'ordre inverse de leur déclaration : le dernier déclaré enveloppe les précédents et voit leurs réponses.


@app.middleware("http")
async def read_only_guard_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Marque une requête de lecture, pour le garde-fou qui interdit de la servir sur une connexion pouvant écrire.

    Déclaré en premier, donc au plus près de la route, où les connexions s'ouvrent.
    """
    if request.method not in READ_ONLY_METHODS:
        return await call_next(request)
    with read_request():
        return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Protège les endpoints d'écriture, hors `/api/auth/` : 401 sans session valide, 403 sans le rôle admin.

    Journalise chaque action admin réussie dans un record `admin_action` (utilisateur, méthode, chemin, statut). Le chemin est celui du routage, sans le préfixe de déploiement.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return await call_next(request)

    # Chemin sans le préfixe de déploiement.
    path = route_path(request.scope)
    if path.startswith("/api/auth/"):
        return await call_next(request)

    user = await anyio.to_thread.run_sync(load_session_user, request.cookies.get("session"))
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Non authentifié"})
    if not user.is_admin:
        return JSONResponse(status_code=403, content={"detail": "Droits insuffisants"})

    # Utilisateur des événements d'audit émis par les services (`emit_event`). `db_conn` écrit ces événements dans `audit_log` avant son commit.
    token_ctx = audit_log.set_current_user(user.login)
    try:
        response = await call_next(request)
    finally:
        audit_log.reset_current_user(token_ctx)

    if response.status_code < 400:
        logger.info(
            "admin_action",
            extra={
                "user": user.login,
                "method": request.method,
                "path": path,
                "status": response.status_code,
            },
        )
    return response


@app.middleware("http")
async def pagination_bounds_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Refuse, sur toutes les routes, une lecture paginée dont le décalage dépasse `MAX_PAGINATION_OFFSET`.

    L'export a le même plafond : le refus oriente vers le filtrage.
    """
    plafond = settings.max_pagination_offset
    offset = requested_offset(request.query_params)
    if offset is not None and offset > plafond:
        return JSONResponse(
            status_code=422,
            content={
                "detail": (
                    f"La pagination demandée saute {offset} lignes, au-delà du plafond de "
                    f"{plafond}. Affiner les filtres pour rapprocher les lignes visées du "
                    "début du résultat."
                )
            },
        )
    return await call_next(request)


@app.middleware("http")
async def read_rate_limit_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Plafonne le nombre de lectures d'une même adresse IP sur les routes `/api/`.

    Les fichiers de l'interface sont exclus du décompte : une page en charge des dizaines sans toucher la base.
    """
    if request.method != "GET" or not route_path(request.scope).startswith("/api/"):
        return await call_next(request)
    if not read_allowed(request):
        return JSONResponse(
            status_code=429,
            content={"detail": "Trop de requêtes. Réessayez dans quelques minutes."},
        )
    return await call_next(request)


@app.middleware("http")
async def timing_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Mesure la durée de chaque requête, pose l'en-tête `X-Response-Time` et journalise un record `request_completed`.

    Déclaré après les middlewares de refus (authentification, pagination, plafond de lectures) : il journalise aussi leurs refus.
    """
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Response-Time"] = f"{duration_ms}ms"

    logger.info(
        "request_completed",
        extra={
            "method": request.method,
            "path": route_path(request.scope),
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


# En-têtes de sécurité posés sur toute réponse. HSTS relève du reverse-proxy TLS.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",  # interdit le MIME-sniffing
    "X-Frame-Options": "DENY",  # anti-clickjacking
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Retire l'accès aux capteurs et périphériques du navigateur, dont aucune page ne se sert.
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), payment=(), usb=()",
    # Une page ouverte depuis l'application (fiche HAL, profil ORCID…) n'a pas de référence vers l'application (`window.opener`).
    "Cross-Origin-Opener-Policy": "same-origin",
    # Refuse aux autres origines le chargement des ressources de l'application hors CORS (image, script, cadre).
    "Cross-Origin-Resource-Policy": "same-origin",
}

_FRAME_ANCESTORS = "frame-ancestors 'none'"
"""Politique de sécurité de contenu des réponses hors API : aucun autre site ne peut les insérer dans un cadre.

`frame-ancestors` agit seulement en en-tête HTTP. Le reste de la politique des pages est dans leur balise `<meta>`, composée par le build du frontend ; les deux politiques s'appliquent ensemble.
"""

_API_CSP = f"default-src 'none'; base-uri 'none'; form-action 'none'; {_FRAME_ANCESTORS}"
"""Politique des réponses de l'API : aucune ressource chargée, d'aucune origine, si un navigateur affiche la réponse comme un document."""

_NO_STORE = "no-store"
"""Interdit à tout cache de conserver une réponse de l'API.

Une même URL d'API rend un corps différent selon la session (la configuration, par exemple) : un cache partagé servirait à un appelant anonyme la réponse destinée à une session admin.
"""


@app.middleware("http")
async def security_headers_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Pose les en-têtes de sécurité sur chaque réponse, et `Cache-Control: no-store` sur les réponses de l'API."""
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if route_path(request.scope).startswith("/api/"):
        response.headers.setdefault("Cache-Control", _NO_STORE)
        response.headers.setdefault("Content-Security-Policy", _API_CSP)
    else:
        response.headers.setdefault("Content-Security-Policy", _FRAME_ANCESTORS)
    return response


# Posé à l'extérieur des middlewares ci-dessus : il lit seul les messages du client et les leur relaie.
app.add_middleware(CancelOnDisconnect)


# ----- CORS -----
#
# Origines listées par `cors_origins`, sans joker : les appels envoient le cookie de session. Vide en production, où l'API sert le frontend ; renseigné en développement, où le frontend a son propre serveur.
#
# Posé à l'extérieur des middlewares de refus : leurs réponses (401, 422, 429) reçoivent les en-têtes CORS, et le navigateur en lit le code.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Déclaré en dernier, donc posé le plus à l'extérieur : tout middleware trouve le préfixe dans la requête.
app.add_middleware(RootPath, root_path=ROOT_PATH)


# ----- Include routers -----

app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(publications.router)
app.include_router(entity_labels.router)
app.include_router(addresses.router)
app.include_router(countries.router)
app.include_router(feedback.router)
app.include_router(structures.router)
app.include_router(persons.router)
app.include_router(contributions.router)
app.include_router(hal_problems.router)
app.include_router(config.router)
app.include_router(perimeters.router)
app.include_router(publishers.router)
app.include_router(serials.router)
app.include_router(monographs.router)
app.include_router(pipeline_runs.router)
app.include_router(subjects.router)
app.include_router(sources.router)


# ----- Frontend SPA (prod) -----
#
# En production, FastAPI sert le frontend buildé (`interfaces/frontend/build`). Monté en dernier, pour que les routes `/api/*` passent d'abord. En développement, vite sert le frontend et le build est absent.
#
# Hors couverture : la branche prise dépend de la présence du build.
if BUILD_DIR.is_dir():  # pragma: no cover
    app.mount("/", SPAStaticFiles(directory=BUILD_DIR, html=True), name="spa")
