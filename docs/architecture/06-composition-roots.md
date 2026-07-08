# Composition roots

*À jour le 2026-06-30.*

Le composition root est l'endroit où les adapters concrets sont **instanciés** et **câblés** aux use-cases. Il a, par nature, le droit d'importer `infrastructure.*` directement — c'est son rôle. Partout ailleurs, on reçoit un port en paramètre.

Les fichiers qui jouent ce rôle :

- `interfaces/api/app.py` — entry point FastAPI (startup, lifespan, middlewares, montage des routers)
- `interfaces/api/deps.py` — factories partagées par les routers : `db_conn_sync` (Connection SA), query services et repositories câblés sur cette Connection
- `run_pipeline.py` — orchestrateur pipeline complet ; ses wrappers `_run_*` sont les composition roots de chaque phase (ouverture de connexion, instanciation des adapters, appel de l'orchestrateur applicatif)
- `interfaces/cli/oneshot/*` — scripts de remédiation ponctuelle

**Seuls** ces fichiers importent `infrastructure.repositories`, `infrastructure.queries.*` ou toute classe `Pg*` concrète.

- **Côté API** : `app.py` / `deps.py` sont les composition roots ; les routers individuels (`interfaces/api/routers/*`) reçoivent leurs dépendances via `Depends(...)` et **n'importent pas** `infrastructure.*` directement. Verrouillé par le contrat `import-linter` "Routers : pas d'import direct de infrastructure".
- **Côté pipeline** : chaque phase est câblée par son wrapper `_run_*` dans `run_pipeline.py`, qui ouvre la connexion, instancie les adapters concrets et appelle l'orchestrateur applicatif de la phase. Les scripts de remédiation ponctuelle (`interfaces/cli/oneshot/*`) suivent le même principe, chacun **étant** son propre composition root. Pas de séparation construct/appel comme côté API ; cohérent avec leur nature one-shot. Pas de contrat `import-linter` sur ces entry points, la discipline reste manuelle : `application/` et `domain/` ne doivent jamais importer `infrastructure/`, et un entry point doit rester un thin wrapper (imports + instanciations + appel d'un use case ; pas de logique métier).
