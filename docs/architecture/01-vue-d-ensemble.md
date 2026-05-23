# Vue d'ensemble

*Document à jour au 2026-05-21.*

Le projet suit une architecture **hexagonale (DDD)**. Le cœur du système est `application/` (use-cases et orchestrateurs), qui dépend de `domain/` (noyau pur). Autour de ce cœur, deux bandes périphériques d'**adapters frères** qui ne se connaissent pas : `interfaces/` (adapters entrants — HTTP, CLI) et `infrastructure/` (adapters sortants — DB, APIs externes, logs). La neutralité entre ces deux bandes repose sur les **ports** (`Protocol`) définis dans `application/ports/`, qui forment une zone neutre dont dépendent tous les autres modules.

```
                  ┌─────────────────────────────┐
                  │  domain/                    │
                  │  entités, value objects,    │
                  │  règles métier pures        │  (zéro I/O)
                  └──────────────▲──────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │  application/               │
                  │  ├─ ports/    (Protocol)    │  ← zone neutre
                  │  └─ use-cases, orchestrateurs
                  └─────▲────────────────▲──────┘
                        │                │
            ┌───────────┘                └──────────────┐
            │                                           │
    ┌───────┴─────────┐                       ┌─────────┴─────────┐
    │  interfaces/    │    ─── ⊥ ───          │  infrastructure/  │
    │  adapters       │   (pas d'import       │  adapters sortants│
    │  entrants :     │   direct l'un de      │  (SQL, APIs       │
    │  routers, CLI   │   l'autre)            │  externes, logs)  │
    └─────────────────┘                       └───────────────────┘
```

## Règles dures

1. **Noyau pur.** `domain/` contient zéro I/O, zéro import externe hormis `stdlib`. Testable sans DB, sans HTTP, sans mock, en millisecondes.

2. **Les ports sont une zone neutre.** `application/ports/*` ne contient que des `Protocol`, pas d'implémentation. L'arborescence interne (`repositories/` pour les agrégats, `api/` / `pipeline/` pour les query services) sert à grouper visuellement, pas à porter des règles d'import distinctes.

3. **Use-cases indépendants des adapters sortants.** `application/` ne peut pas importer `infrastructure/`. Les services applicatifs reçoivent leurs dépendances (repositories, query services) via les **ports** (`Protocol`) définis dans `application/ports/` — c'est `infrastructure/` qui implémente les ports, pas l'inverse. Contrôlé par `import-linter` (contrat `layered` dans `pyproject.toml`).

4. **Routers ⊥ adapters sortants.** Les routers FastAPI (`interfaces/api/routers/*`) reçoivent leurs dépendances via `Depends(...)` (factories dans `interfaces.api.deps`) ; ils n'instancient pas eux-mêmes les `Pg*` concrets. Verrouillé par un contrat `import-linter`. Les exceptions assumées (deux modules qui importent un utilitaire non-DB) sont déclarées dans le `pyproject.toml`, pas ici. Les scripts CLI ne sont pas concernés : ils sont leur propre composition root (cf. règle 5).

5. **Le composition root est un endroit précis.** L'instanciation concrète des adapters et leur câblage aux use-cases se fait dans **un petit ensemble nommé de fichiers** :

   - `interfaces/api/app.py` + `interfaces/api/deps.py` — API HTTP
   - `run_pipeline.py` — pipeline complet
   - `interfaces/cli/pipeline/*` — phases pipeline isolées
   - `interfaces/cli/*` — scripts one-shot

   Ces fichiers sont les **seuls** qui ont légitimement le droit d'importer `infrastructure.repositories`, `infrastructure.queries.*` ou toute classe `Pg*` concrète. Partout ailleurs, on passe par un port.

Le contrat `layers` d'`import-linter` (voir `pyproject.toml`, section `[tool.importlinter]`) vérifie les règles 1 à 3. Le contrat `forbidden` "Routers : pas d'import direct de infrastructure" applique la règle 4. Le contrat `forbidden` "Composition root : Pg* concrets uniquement dans app et deps" applique la règle 5 pour `interfaces/api/` (les CLIs restent discipline-only — ils sont leur propre composition root par nature, cf. règle 5).

## Suite

Détail couche par couche :
- [`domain/`](domain) — noyau métier pur
- [`application/`](application) — services, orchestrateurs, patterns d'injection
- [`infrastructure/`](infrastructure) — adapters sortants, discipline transactionnelle
- [`interfaces/`](interfaces) — adapters entrants, sync threadpool
- [Composition roots](composition-roots) — qui a le droit d'importer quoi
- [Tests](tests) — unit, intégration, coverage
