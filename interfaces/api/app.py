"""Bibliométrie UCA — application FastAPI : point d'assemblage de la surface HTTP.

Câble le cycle de vie de l'engine SQLAlchemy, la traduction des erreurs métier en codes HTTP, les middlewares (authentification des écritures, mesure de durée), les routers, et le service du frontend buildé.

Lancement en développement : `bash start.sh`, qui démarre uvicorn sur le port 8000 et le serveur de développement du frontend.
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
from sqlalchemy.exc import IntegrityError
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
from infrastructure.db.read_only_guard import read_request
from infrastructure.observability.log import configure_root_logging
from infrastructure.settings import settings
from interfaces.api.deps import READ_ONLY_METHODS
from interfaces.api.models.errors import (
    PublisherMergeBlockedResponse,
    RejectedPairsResponse,
)
from interfaces.api.params import requested_offset
from interfaces.api.rate_limit import read_allowed
from interfaces.api.route_path import route_path
from interfaces.api.session import check_auth_config, read_session
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
    entity_labels,
    feedback,
    hal_problems,
    journals,
    perimeters,
    persons,
    pipeline_runs,
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
    check_auth_config()
    sync_engine = build_sync_engine("app")
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
# Docs interactives coupées par défaut (`expose_api_docs`) : elles cartographient toute la
# surface d'API, admin comprise. Activées en développement, absentes en production.
_docs_urls = (
    {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    if settings.expose_api_docs
    else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)
app = FastAPI(
    title="Bibliométrie UCA",
    lifespan=lifespan,
    root_path=os.environ.get("ROOT_PATH", ""),
    **_docs_urls,
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


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Traduit une violation de contrainte d'intégrité en 409, plutôt qu'un 500 opaque.

    Couvre uniformément toute écriture qui heurte une contrainte de la base sur une requête bien formée : clé étrangère vers une entité inexistante, doublon sur un index unique, condition CHECK non tenue. Le détail SQL reste au log — il expose la structure interne et n'éclaire pas l'appelant.
    """
    logger.warning("Violation d'intégrité sur %s %s : %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=409,
        content={"detail": "La requête viole une contrainte d'intégrité des données."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Renvoie du JSON 500 au lieu de HTML pour les erreurs non gérées."""
    logger.error(
        "Erreur non gérée sur %s %s\n%s", request.method, request.url.path, traceback.format_exc()
    )
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur"})


# ----- Middleware -----
#
# Starlette empile les middlewares dans l'ordre inverse de leur déclaration : le dernier
# déclaré enveloppe les précédents, et voit donc toutes les réponses, y compris celles qu'un
# middleware intérieur compose sans laisser passer la requête.


@app.middleware("http")
async def read_only_guard_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Déclare la requête de lecture, pour le garde-fou qui refuse qu'une connexion pouvant écrire la serve.

    Déclaré en premier, donc posé au plus près de la route : la déclaration couvre le traitement de la requête, où les connexions s'ouvrent.
    """
    if request.method not in READ_ONLY_METHODS:
        return await call_next(request)
    with read_request():
        return await call_next(request)


@app.middleware("http")
async def auth_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    """Protège les endpoints d'écriture (POST/PUT/DELETE/PATCH), hors authentification.

    Journalise les actions admin réussies (statut < 400) sous le record structuré `admin_action`, qui porte l'utilisateur, la méthode, le chemin et le statut. Le chemin journalisé est celui du routage, indépendant du préfixe sous lequel l'application est servie : une même action porte le même nom d'un déploiement à l'autre.
    """
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return await call_next(request)

    # Chemin privé du préfixe de déploiement, celui sur lequel le routage apparie ses routes.
    path = route_path(request.scope)
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
async def pagination_bounds_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Refuse une lecture paginée dont le décalage dépasse `MAX_PAGINATION_OFFSET`.

    La garde est posée au niveau du transport plutôt que route par route : les listes déclarent leur pagination chacune de leur côté, et une route ajoutée plus tard hérite du plafond sans intervention. Le coût d'une lecture profonde tient au produit du rang par la taille de page, non au rang seul — c'est donc le décalage qui se borne.

    Le recours qu'annonce le refus est le filtrage, seul moyen de rapprocher les lignes visées du début du résultat : l'export porte le même plafond et ne rend pas davantage.
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
    """Plafonne les lectures d'une même adresse, sur l'ensemble des points d'entrée de l'API.

    Le plafond de lignes borne ce qu'une lecture coûte ; celui-ci borne ce que leur répétition coûte. Un point d'entrée en lecture ajouté plus tard en hérite sans intervention.

    Les fichiers de l'interface sortent du décompte : une page en tire des dizaines, sans toucher la base.
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
    """Mesure la durée de chaque requête, pose l'en-tête `X-Response-Time` et journalise un record structuré `request_completed`.

    Déclaré après les middlewares qui composent un refus sans laisser passer la requête, il les enveloppe donc et voit leurs réponses : les refus d'authentification, de pagination et de plafond de lectures paraissent au journal comme les requêtes servies. Un refus qui n'y paraîtrait pas serait invisible — un moissonnage bridé par le plafond ne laisserait aucune trace.
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
    "X-Frame-Options": "DENY",  # anti-clickjacking (l'appli ne s'iframe jamais)
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Retire à la page l'accès aux capteurs et périphériques du navigateur. Aucune n'en
    # demande ; le déclarer ferme la porte à du code qui parviendrait à s'exécuter dans la page.
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(), payment=(), usb=()",
    # Isole le contexte de navigation : une page ouverte depuis l'application — fiche HAL,
    # profil ORCID, identifiant ROR — perd la référence vers celle qui l'a ouverte. `rel="noopener"`
    # pose la même garantie lien par lien ; celle-ci vaut pour tous, sans dépendre de l'attribut.
    "Cross-Origin-Opener-Policy": "same-origin",
}

_FRAME_ANCESTORS = "frame-ancestors 'none'"
"""Politique de sécurité de contenu posée sur toute réponse : la page ne peut être insérée dans le cadre d'un autre site.

C'est la formulation que les navigateurs traitent aujourd'hui comme la référence de l'anti-clickjacking, `X-Frame-Options` en étant l'ancêtre — les deux sont posés, le second pour les navigateurs qui ne lisent que lui.

La directive n'a d'effet qu'en en-tête : une politique portée par une balise `<meta>` l'ignore. C'est ce qui la distingue de la politique des pages du frontend, que le générateur du frontend compose page par page — elle y autorise nommément les scripts de l'application par leur empreinte, ce que le serveur ne saurait pas reproduire. Les deux politiques s'appliquent alors ensemble sur une page, et une réponse doit satisfaire l'une comme l'autre ; celle-ci ne déclarant que `frame-ancestors`, elle ne restreint rien de ce que l'autre autorise.
"""

_API_CSP = f"default-src 'none'; base-uri 'none'; form-action 'none'; {_FRAME_ANCESTORS}"
"""Politique des réponses de l'API, qui ne rendent que du JSON : aucune ressource, d'aucune sorte, d'aucune origine.

Une réponse d'API n'est pas un document, et rien n'oblige un navigateur à la traiter comme telle : une navigation directe vers un point d'entrée, une réponse d'erreur, un point d'entrée qui rendrait un jour autre chose que du JSON. `X-Content-Type-Options` retire au navigateur la liberté de réinterpréter le type déclaré ; celle-ci retire au document qu'il en ferait quand même le droit de charger ou d'exécuter quoi que ce soit.
"""

_NO_STORE = "no-store"
"""Interdiction de conserver une copie de la réponse, adressée à tout cache du chemin.

Faute de consigne, un cache applique ses propres heuristiques et peut ranger une réponse pour la resservir à un autre appelant. Or une même adresse d'API ne rend pas toujours le même corps : la configuration se restreint à une liste blanche de clés sans session et s'ouvre avec, sur la même URL. Un cache partagé — le reverse-proxy, un proxy d'entreprise sur le chemin — qui garderait la réponse servie à une session ouverte la rendrait ensuite à un appelant anonyme.

L'interface, elle, garde son cache : ses fichiers portent leur empreinte dans leur nom, et c'est ce qui rend une page rapide au second chargement.
"""


@app.middleware("http")
async def security_headers_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Pose les en-têtes de sécurité (anti-sniffing, anti-clickjacking, politique de référent, politique de sécurité de contenu) sur chaque réponse, et l'interdiction de mise en cache sur les réponses de l'API."""
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if route_path(request.scope).startswith("/api/"):
        response.headers.setdefault("Cache-Control", _NO_STORE)
        response.headers.setdefault("Content-Security-Policy", _API_CSP)
    else:
        response.headers.setdefault("Content-Security-Policy", _FRAME_ANCESTORS)
    return response


# ----- CORS -----
#
# Origines énumérées par `cors_origins`, qui refuse le joker : les appels portent le cookie de
# session, et `*` reviendrait à autoriser toute origine à s'en servir. Vide en production, où le
# frontend est servi par l'API elle-même ; renseigné en développement, le serveur de
# développement du frontend vivant sur un autre port.
#
# Déclaré en dernier, donc posé le plus à l'extérieur : les refus que composent les middlewares
# ci-dessus — 401 d'authentification, 429 des plafonds, 422 de pagination — portent alors les
# en-têtes CORS comme les autres réponses. Sans cela, le navigateur d'une origine autorisée les
# reçoit comme une erreur CORS opaque au lieu de leur code, et le message de refus est perdu.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
app.include_router(authorships.router)
app.include_router(hal_problems.router)
app.include_router(config.router)
app.include_router(perimeters.router)
app.include_router(publishers.router)
app.include_router(journals.router)
app.include_router(pipeline_runs.router)
app.include_router(subjects.router)


# ----- Frontend SPA (prod) -----
#
# En prod, le frontend buildé (adapter-static) est servi par FastAPI : la SPA
# (ssr=false) et les docs prérendues vivent dans interfaces/frontend/build.
# Monté en dernier — catch-all — pour que les routes /api/* matchent d'abord.
# Absent en dev (vite sert le frontend) : on ne monte que si le build existe.
if BUILD_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=BUILD_DIR, html=True), name="spa")
