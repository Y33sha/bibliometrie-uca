# Interfaces — adapters entrants

*À jour le 2026-06-30.*

Contenu :

- **`api/`** — FastAPI :
  - `app.py` — entry point (routers, middlewares, gestion d'erreurs)
  - `routers/` — un module par agrégat (publications, persons, laboratories, addresses, …)
  - `models/` — Pydantic pour les bodies POST/PUT/PATCH (un module par agrégat)
  - `deps.py` — dépendances (Engine SA sync, factories de query services et de repositories, auth)
  - middlewares inline dans `app.py` (auth, strip-prefix, timing)
- **`frontend/`** — SvelteKit (Svelte 5)
- **`cli/`** — scripts (imports manuels, debug, corrections ponctuelles). Exclus de la couverture pytest (`[tool.coverage.run]` omit).

## Sync partout (FastAPI + threadpool)

Toutes les routes API sont déclarées `def` (pas `async def`). FastAPI les exécute dans le threadpool Starlette (~40 workers par défaut), ce qui permet de partager **les mêmes** repositories et query services entre l'API et le pipeline. Une seule famille de code, un seul style de connexion (`Connection` SQLAlchemy).

Aucun *handler* de route n'est `async` : les seules fonctions `async def` sont des constructions de framework dans `app.py` (lifespan, gestionnaires d'erreurs, middlewares d'authentification et de chronométrage), comme l'impose Starlette. Elles ne touchent pas la base.

Dimensionnement du pool DB : `db_pool_max = 30` (dans `infrastructure/settings.py`), pour absorber confortablement la concurrence threadpool × marge sur un usage admin (quelques utilisateurs concurrents max). Bumper si on observe des `TimeoutError` côté pool sous charge anormale (cf. `.env.example`).
