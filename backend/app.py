"""
Bibliométrie UCA — API FastAPI.

Usage:
    cd publisher-stats
    python webapp/app.py

Puis ouvrir http://localhost:8003
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse

from backend.deps import _verify_token

from backend.routers import (
    auth, pub_stats, publications, admin_duplicates,
    addresses, feedback, laboratories, stats,
    structures, authorships, persons, admin_person_duplicates,
    docs,
)

app = FastAPI(title="Bibliométrie UCA")

# ----- CORS (frontend SvelteKit sur port séparé) -----

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5176", "http://localhost:5173", "http://127.0.0.1:5176"],
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
        request.scope["path"] = request.url.path[len("/bibliometrie"):]
    return await call_next(request)


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


if __name__ == "__main__":
    import uvicorn
    print("Démarrage du serveur sur http://localhost:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003)
