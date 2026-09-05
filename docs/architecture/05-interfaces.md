# Interfaces — adaptateurs entrants

*À jour le 2026-09-05.*

`interfaces/` reçoit les demandes extérieures et les traduit en appels aux use-cases : HTTP pour l'API et le frontend, ligne de commande pour le pipeline et les scripts.

## Contenu

- **`api/`** — l'application FastAPI.
  - `app.py` assemble les routers, la traduction des erreurs métier en codes HTTP, et les middlewares (authentification des écritures, plafonds de lecture, en-têtes de sécurité, journalisation des requêtes) ;
  - `routers/` et `models/` contiennent un module par agrégat ;
  - `deps.py` porte les fabriques que les routes reçoivent par `Depends`.
  - S'y ajoutent la session d'administration (`session.py`), les limiteurs de débit (`rate_limit.py`) et le service du frontend buildé (`spa.py`).
- **`frontend/`** — l'application SvelteKit (Svelte 5), servie par l'API une fois buildée.
- **`cli/`** — les programmes lancés en ligne de commande :
  - `run_pipeline.py` — l'orchestrateur du pipeline, installé comme commande `run_pipeline`
  - `imports/` — imports de fichiers externes (frais de publication, DOAJ, personnes)
  - `maintenance/` — opérations rejouables sur la base
  - `dev/` — production des artefacts du dépôt : schéma SQL, contrat OpenAPI, jeu de données de démarrage
  - `oneshot/` — scripts écrits pour une seule exécution, conservés comme trace ; exclus de la mesure de couverture `pytest`

## Routes synchrones

Aucune route n'est `async def`. FastAPI les exécute donc dans le threadpool de Starlette, ce qui permet à l'API et au pipeline de partager les mêmes repositories et query services, sur le même type de connexion. Les seules fonctions `async` sont les constructions qu'impose Starlette — cycle de vie, gestionnaires d'erreurs, middlewares — et aucune ne touche la base.

La concurrence de l'API est donc celle du threadpool, dimensionné par `API_THREADPOOL_SIZE`. Le plafond du pool de connexions (`DB_POOL_MAX`) doit être au moins égal.
