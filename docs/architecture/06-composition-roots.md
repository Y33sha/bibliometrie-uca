# Composition roots

*À jour le 2026-06-30.*

Le composition root est l'endroit où les adapters concrets sont **instanciés** et **câblés** aux use-cases. Il a, par nature, le droit d'importer `infrastructure.*` directement — c'est son rôle. Partout ailleurs, on reçoit un port en paramètre.

Les fichiers qui jouent ce rôle :

- `interfaces/api/app.py` — entry point FastAPI (startup, lifespan, middlewares, montage des routers)
- `interfaces/api/deps.py` — factories partagées par les routers : `db_conn` (Connection SA), read-models, repositories et gateways pipeline câblés dessus, plus les lanceurs de tâches de fond
- `run_pipeline.py` — orchestrateur pipeline complet ; ses wrappers `_run_*` sont les composition roots de chaque phase (ouverture de connexion, instanciation des adapters, appel de l'orchestrateur applicatif)
- `interfaces/cli/imports/*` et `interfaces/cli/maintenance/*` — imports et opérations de maintenance permanents ; chaque script instancie repository ou gateway et appelle le service

**Seuls** ces fichiers importent `infrastructure.repositories`, `infrastructure.read_models`, `infrastructure.pipeline` ou toute classe `Pg*` concrète.

- **Côté API** : `app.py` / `deps.py` sont les composition roots ; les routers individuels (`interfaces/api/routers/*`) reçoivent leurs dépendances via `Depends(...)` et **n'importent pas** `infrastructure.*` directement. Verrouillé par le contrat `import-linter` "Routers : pas d'import direct de infrastructure".
- **Côté pipeline et CLI** : chaque phase est câblée par son wrapper `_run_*` dans `run_pipeline.py`, qui ouvre la connexion, instancie les adapters concrets et appelle l'orchestrateur applicatif de la phase. Chaque script `interfaces/cli/*` est de même son propre composition root, sans la séparation construct/appel de l'API. Le contrat `import-linter` "Composition root" ne couvre que l'API (`source_modules = ["interfaces.api"]`) : hors API, la discipline reste manuelle — `application/` et `domain/` n'importent jamais `infrastructure/`, et un entry point reste un thin wrapper (imports + instanciations + appel d'un use case ; pas de logique métier).
