"""
Bibliométrie UCA — API FastAPI.

Usage:
    cd publisher-stats
    python webapp/app.py

Puis ouvrir http://localhost:8003
"""

import logging
import os
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from backend.deps import _verify_token, get_cursor
from backend.routers import (
    addresses,
    admin_duplicates,
    admin_person_duplicates,
    auth,
    authorships,
    config,
    docs,
    feedback,
    journals,
    laboratories,
    persons,
    pipeline,
    pub_stats,
    publications,
    publishers,
    stats,
    structures,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Bibliométrie UCA")


# ----- Exception handler global -----


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
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
async def auth_middleware(request: Request, call_next):
    """Protège les endpoints d'écriture (POST/PUT/DELETE/PATCH) sauf auth."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        path = request.scope["path"]
        if not path.startswith("/api/auth/"):
            token = request.cookies.get("session")
            if not token or not _verify_token(token):
                return JSONResponse(status_code=401, content={"detail": "Non authentifié"})
    return await call_next(request)


@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    """Strip /bibliometrie prefix pour que les routes /api/* fonctionnent en accès direct."""
    if request.url.path.startswith("/bibliometrie/api/"):
        request.scope["path"] = request.url.path[len("/bibliometrie") :]
    return await call_next(request)


# ----- Health check -----


@app.get("/api/health")
async def health():
    """Vérifie que l'API est opérationnelle et la DB accessible."""
    import os

    sandbox = os.environ.get("BIBLIOMETRIE_SANDBOX") == "1"
    try:
        with get_cursor() as (cur, conn):
            cur.execute("SELECT 1")
        return {"status": "ok", "db": "ok", "sandbox": sandbox}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "db": str(e)})


# ----- Root redirect -----


@app.get("/")
async def root():
    return RedirectResponse("/bibliometrie/stats")


# ----- Include routers -----

app.include_router(auth.router)
app.include_router(pub_stats.router)
app.include_router(publications.router)
app.include_router(admin_duplicates.router)
app.include_router(addresses.router)
app.include_router(feedback.router)
app.include_router(laboratories.router)
app.include_router(stats.router)
app.include_router(structures.router)
app.include_router(authorships.router)
app.include_router(persons.router)
app.include_router(admin_person_duplicates.router)
app.include_router(docs.router)
app.include_router(config.router)
app.include_router(publishers.router)
app.include_router(journals.router)
app.include_router(pipeline.router)


if __name__ == "__main__":
    import uvicorn

    print("Démarrage du serveur sur http://localhost:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003)
