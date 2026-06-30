# Vue d'ensemble

*À jour le 2026-06-30.*

Le système se lit selon deux axes complémentaires : **deux runtimes** couplés par la base de données (vue d'exécution), et **quatre couches** organisant le code à l'intérieur de chaque runtime (vue logicielle).

## Deux runtimes, une base

Le code héberge deux programmes de natures différentes, qui ne s'appellent jamais directement : ils ne communiquent qu'à travers la base PostgreSQL, laquelle constitue leur **contrat d'intégration**.

- **Le service en ligne** (`interfaces/api/` + `interfaces/frontend/`) : un processus FastAPI long, piloté par les requêtes des utilisateurs. Il est essentiellement une **couche de lecture** sur des données pré-calculées (projections plates, agrégations, facettes), avec une surface d'écriture restreinte à la **curation humaine**.
- **Le pipeline** (`run_pipeline.py` + `application/pipeline/`) : un traitement par lots, déclenché par un ordonnanceur. Il **dérive** le référentiel : moissonnage des sources, normalisation, déduplication, rapprochement, enrichissements.

```
  sources externes (HAL, OpenAlex, WoS, ScanR, theses.fr)
        │
        ▼  moissonnage
  ┌──────────────┐                ┌──────────────────────────┐               ┌───────────────┐
  │   pipeline   │ ── écrit ────► │        PostgreSQL        │ ── lit ─────► │  service en   │ ◄── utilisateurs
  │   (batch)    │   (dérive)     │  (contrat d'intégration) │               │  ligne (API   │
  │              │ ◄── relit ──── │                          │ ◄── écrit ─── │  + frontend)  │
  └──────────────┘   la curation  └──────────────────────────┘   curation    └───────────────┘
```

Les extracteurs du pipeline sont le point d'entrée des données dans le système : le pipeline moissonne les sources, en dérive le référentiel qu'il écrit dans PostgreSQL, d'où le service en ligne lit. Seule la curation remonte ce courant — de l'API vers la base, puis relue par le pipeline.

La curation forme une **boucle fermée** : les corrections saisies via l'API — données de référence (structures, périmètre, configuration) et décisions de séparation (*cannot-link* entre personnes ou entre publications) — deviennent des **entrées** que le pipeline relit et **préserve** à chaque passe. Ses traitements étant idempotents, une re-dérivation n'écrase jamais une décision humaine.

Il en découle une frontière de **propriété des données**, transverse aux couches : certaines tables sont dérivées par le pipeline (recalculables, l'API ne fait que les lire), d'autres sont saisies par l'humain (l'API les écrit, le pipeline les respecte sans jamais les écraser). Cette frontière conditionne toute reprise du système et se décline table par table dans [le modèle de données](../donnees/).

## Vue par couches

Le projet suit une architecture **hexagonale (DDD)**. Le cœur du système est `application/` (use-cases et orchestrateurs), qui dépend de `domain/` (noyau pur). Autour de ce cœur, deux bandes périphériques d'**adapters frères** qui ne se connaissent pas : `interfaces/` (adapters entrants — HTTP, CLI) et `infrastructure/` (adapters sortants — DB, APIs externes, logs). La neutralité entre ces deux bandes repose sur les **ports** (`Protocol`) définis dans `application/ports/`, qui forment une zone neutre dont dépendent tous les autres modules.

Cette vue par couches se superpose à la vue par runtime : `application/` et `infrastructure/` sont chacune scindées entre un versant lecture (consommé par le service en ligne) et un versant pipeline, tandis que `domain/` reste commun aux deux.

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

2. **Les ports sont une zone neutre.** `application/ports/*` ne contient que des `Protocol`, pas d'implémentation.

3. **Use-cases indépendants des adapters sortants.** `application/` ne peut pas importer `infrastructure/`. Les services applicatifs reçoivent leurs dépendances (repositories, query services) via les **ports** (`Protocol`) définis dans `application/ports/` — c'est `infrastructure/` qui implémente les ports, pas l'inverse. Contrôlé par `import-linter` (contrat `layers` dans `pyproject.toml`).

4. **Routers ⊥ adapters sortants.** Les routers FastAPI (`interfaces/api/routers/*`) reçoivent leurs dépendances via `Depends(...)` (factories dans `interfaces.api.deps`) ; ils n'instancient pas eux-mêmes les `Pg*` concrets. Verrouillé par un contrat `import-linter`. Les scripts CLI ne sont pas concernés : ils sont leur propre composition root (cf. règle 5).

5. **Le composition root est un endroit précis.** L'instanciation concrète des adapters et leur câblage aux use-cases se fait dans **un petit ensemble nommé de fichiers** :

   - `interfaces/api/app.py` + `interfaces/api/deps.py` — API HTTP
   - `run_pipeline.py` — pipeline complet
   - `interfaces/cli/*` — scripts CLI

   Ces fichiers sont les **seuls** qui ont légitimement le droit d'importer `infrastructure.repositories`, `infrastructure.queries.*` ou toute classe `Pg*` concrète. Partout ailleurs, on passe par un port.

Le contrat `layers` d'`import-linter` (voir `pyproject.toml`, section `[tool.importlinter]`) vérifie les règles 1 à 3. Le contrat `forbidden` "Routers : pas d'import direct de infrastructure" applique la règle 4. Le contrat `forbidden` "Composition root : Pg* concrets uniquement dans app et deps" applique la règle 5 pour `interfaces/api/` (les CLIs restent discipline-only — ils sont leur propre composition root par nature, cf. règle 5).

## Suite

Détail couche par couche :
- [`domain/`](02-domain.md) — noyau métier pur
- [`application/`](03-application.md) — services, orchestrateurs, patterns d'injection
- [`infrastructure/`](04-infrastructure.md) — adapters sortants, discipline transactionnelle
- [`interfaces/`](05-interfaces.md) — adapters entrants, sync threadpool
- [Composition roots](06-composition-roots.md) — qui a le droit d'importer quoi
- [Tests](07-tests.md) — unit, intégration, coverage
