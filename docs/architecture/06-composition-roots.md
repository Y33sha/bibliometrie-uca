# Composition roots

Le composition root est l'endroit où les adapters concrets sont **instanciés** et **câblés** aux use-cases. Il a, par nature, le droit d'importer `infrastructure.*` directement — c'est son rôle. Partout ailleurs, on reçoit un port en paramètre.

Les fichiers qui jouent ce rôle :

- `interfaces/api/app.py` — entry point FastAPI (startup, lifespan, middlewares, montage des routers)
- `interfaces/api/deps.py` — factories partagées par les routers : `db_conn_sync` (Connection SA), query services et repositories câblés sur cette Connection
- `run_pipeline.py` — orchestrateur pipeline complet
- `interfaces/cli/*` — scripts CLI

**Seuls** ces fichiers importent `infrastructure.repositories`, `infrastructure.queries.*` ou toute classe `Pg*` concrète.

- **Côté API** : `app.py` / `deps.py` sont les composition roots ; les routers individuels (`interfaces/api/routers/*`) reçoivent leurs dépendances via `Depends(...)` et **n'importent pas** `infrastructure.*` directement. Verrouillé par le contrat `import-linter` "Routers : pas d'import direct de infrastructure".
- **Côté CLI** : chaque script (`interfaces/cli/*`, y compris `interfaces/cli/pipeline/*`) **est** son propre composition root. Il importe les adapters concrets, instancie les factories, et appelle un use case applicatif en lui passant tout en kwargs. Pas de séparation construct/appel comme côté API ; cohérent avec la nature one-shot des scripts. Pas de contrat `import-linter` côté CLI, la discipline reste manuelle : `application/` et `domain/` ne doivent jamais importer `infrastructure/`, et le script CLI doit rester un thin wrapper (imports + instanciations + appel d'un use case ; pas de logique métier dans le script).
