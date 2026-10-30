# Interfaces — adaptateurs entrants

*À jour le 2026-09-05.*

`interfaces/` reçoit les demandes extérieures et les traduit en appels aux services : HTTP pour l'API et le frontend, ligne de commande pour les scripts.

## Contenu

- **`api/`** — l'application FastAPI.
  - `app.py` assemble les routers, la traduction des erreurs métier en codes HTTP, et les middlewares (authentification des écritures, plafonds de lecture, en-têtes de sécurité, journalisation des requêtes) ;
  - `routers/` contient un module par ressource, `models/` les corps des requêtes d'écriture ;
  - `deps.py` contient les fabriques reçues par les routes via `Depends`.
  - S'y ajoutent la session d'administration (`session.py`), les limiteurs de débit (`rate_limit.py`) et le service du frontend buildé (`spa.py`).
- **`frontend/`** — l'application SvelteKit (Svelte 5), servie par l'API une fois buildée.
- **`cli/`** — les programmes lancés en ligne de commande :
  - `imports/` — imports de fichiers externes (frais de publication, DOAJ, personnes, dump ROR)
  - `maintenance/` — opérations rejouables sur la base
  - `dev/` — outils de développement : artefacts du dépôt (schéma SQL, contrat OpenAPI, seed), migrations, instances, captures d'écran
  - `oneshot/` — scripts écrits pour une seule exécution, conservés comme trace

## Routes synchrones

Les routes sont synchrones : FastAPI les exécute dans le threadpool d'anyio. Les fonctions `async` sont seulement celles qu'impose Starlette (cycle de vie, gestionnaires d'erreurs, middlewares), et aucune ne touche la base.

La concurrence de l'API est donc celle du threadpool, dimensionné par `API_THREADPOOL_SIZE`. Le plafond du pool de connexions (`DB_POOL_MAX`) doit être au moins égal.
