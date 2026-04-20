# Architecture logicielle — Bibliométrie UCA

Pour le modèle de données (tables, relations, domaines fonctionnels),
voir [donnees.md](donnees.md).

## Vue d'ensemble

Le projet suit une architecture **hexagonale (DDD)** en 4 couches
distinctes, vérifiées par `import-linter` en pre-commit et en CI.

```
┌─────────────────────────────────────────────────────────┐
│  interfaces/       (adapters entrants — HTTP / CLI)     │
│  ├─ api/           FastAPI : routers, middlewares       │
│  ├─ frontend/      SvelteKit                            │
│  └─ cli/           Scripts one-shot (imports, debug)    │
└────────────────────┬────────────────────────────────────┘
                     │ peut importer tout le reste
       ┌─────────────┴─────────────┐
       ▼                           ▼
┌─────────────────┐         ┌──────────────────────────┐
│  application/   │         │  infrastructure/          │
│  services,      │  ───✗   │  adapters sortants (SQL,  │
│  orchestrateurs │  (port) │  APIs, settings, logs)    │
└────────┬────────┘         └──────────────┬────────────┘
         │                                 │
         └────────────────┬────────────────┘
                          ▼
                  ┌───────────────┐
                  │  domain/      │
                  │  entités,     │
                  │  value objects│
                  │  règles pures │
                  └───────────────┘
```

Règles dures :

- `domain/` est le noyau pur : **zéro I/O**, zéro import externe
  (hormis stdlib). Peut être unit-testé sans DB, sans HTTP, sans
  mock.
- `application/` et `infrastructure/` sont **siblings** : ni l'un ni
  l'autre ne peut importer l'autre directement. Leurs interactions
  passent par des **ports** (Protocol) définis dans `application/ports/`
  ou `domain/ports/`.
- `interfaces/` peut tout importer ; c'est le niveau composition root.

Le contrat `layers` est dans `pyproject.toml` (`[tool.importlinter]`).
Toute violation fait échouer pre-commit et la CI.

## Les 4 couches en détail

### `domain/` — noyau métier pur

Contenu :
- **Value objects** : `DOI`, `ORCID`, `IdRef`, normalisation de noms
  (`names.py`, `normalize.py`), identité ORCID/idHAL
- **Modèles métier** : représentations immutables (dataclasses) avec
  invariants (`publication.py`, `person.py`, `structure.py`)
- **Règles métier pures** : `doc_types`, `authorship_roles`, `sources`
  (enum des 5 sources)
- **Ports repositories** (`domain/ports/*`) : interfaces Protocol pour
  `PersonRepository`, `PublicationRepository`, `JournalRepository`,
  `StructureRepository`, `AuthorshipRepository`, `AddressRepository`,
  `ConfigRepository`

Le domaine est testé en unit sans DB.

### `application/` — services et orchestrateurs

Contenu :
- **Services métier** : `persons.py`, `publications.py`, `journals.py`,
  `authorships.py`, `structures.py`, `addresses.py`, `audit.py`,
  `config.py`. Ces services reçoivent leurs dépendances par injection
  (kwarg `repo=`, cf. §1.7b de la ROADMAP).
- **Orchestrateurs pipeline** dans `application/pipeline/` :
  - `normalize/` — staging → tables sources (un module par source)
  - `build/` — construction authorships, affiliations, name_forms
  - `create/` — création publications, personnes
  - `merge/` — fusions inter-sources (DOI, HAL-ID, NNT)
  - `enrich/` — Unpaywall, APC
  - `harvest/` — identifiants HAL (ORCID, IdRef)
  - `countries/` — détection pays, refresh
  - `addresses/` — résolution adresses → structures
- **Ports** (`application/ports/*`) : interfaces Protocol pour les
  query services (adapters dans `infrastructure/db/queries/*`).

Interdiction : **`application/` ne peut pas importer
`infrastructure/`**. 15 violations historiques grandfathered dans
`ignore_imports` (pipeline normalize_* qui utilisent encore
`infrastructure.addresses`, `db_helpers`, `zenodo`, `openalex`,
`timings`, `perimeter`). Chaque nettoyage = une ligne retirée
(cf. ROADMAP §1.7b).

### `infrastructure/` — adapters sortants

Contenu :
- **`db/`** :
  - `schema.sql`, `seed.sql`
  - `migrations/` — migrations numérotées, appliquées via
    `python -m infrastructure.db.migrate`
  - `queries/` — query services SQL (un par agrégat ou phase
    pipeline) ; implémentent les ports définis dans `application/
    ports/*`
  - `connection.py` — pool psycopg2
- **`repositories/`** — adapters PostgreSQL implémentant les ports
  `domain/ports/*` : `person_repository.py`, `publication_repository.py`,
  `journal_repository.py`, `structure_repository.py`,
  `authorship_repository.py`, `address_repository.py`,
  `config_repository.py`. Factories exposées dans `__init__.py`
  (`person_repository(cur)`, `publication_repository(cur)`, …).
- **`sources/`** — extracteurs API (HAL, OpenAlex, WoS, ScanR,
  theses.fr). Héritent de `SourceExtractor` (`base.py`).
- **Divers** : `log.py` (JSON structuré), `settings.py`
  (pydantic-settings), `perimeter.py`, `addresses.py`, `zenodo.py`,
  `api_retry.py`, `api_limits.py`, `pipeline_metrics.py`.

Interdiction : **`infrastructure/` ne peut pas importer
`application/`** (sauf par un port explicitement passé).

### `interfaces/` — adapters entrants

Contenu :
- **`api/`** — FastAPI :
  - `app.py` — entry point (routers, middlewares, gestion d'erreurs)
  - `routers/` — un module par agrégat (publications, persons,
    laboratories, addresses, …)
  - `models.py` — Pydantic pour les bodies POST/PUT/PATCH
  - `deps.py` — dépendances (pool DB, auth)
  - `middlewares/` — request-id, audit, timing
- **`frontend/`** — SvelteKit (Svelte 5)
- **`cli/`** — scripts one-shot (imports manuels, debug, corrections
  ponctuelles). Exclus de la couverture pytest
  (`[tool.coverage.run]` omit).

## Patterns d'injection

### Services applicatifs ↔ repositories

Les services acceptent leur repo en kwarg :

```python
def set_rejected(cur: Any, person_id: int, rejected: bool, *,
                 repo: PersonRepository) -> None:
    repo.set_rejected(person_id, rejected)
```

Les callers directs (routers, tests, scripts CLI) créent l'instance
via la factory :

```python
from infrastructure.repositories import person_repository
set_rejected(db, person_id, True, repo=person_repository(db))
```

### Orchestrateurs pipeline ↔ query services + repositories

Les orchestrateurs dans `application/pipeline/*` ne peuvent pas
importer `infrastructure.*` directement. Deux mécanismes :

1. **Query services** (SQL de la phase) : passés en paramètre
   typés par un port `application/ports/*`. L'entry point
   (`run_pipeline.py` ou `interfaces/cli/pipeline/*`) instancie les
   adapters `Pg*Queries` concrets.

2. **Repositories** (ex. `PublicationRepository`) : quand un
   orchestrateur a besoin d'un repo, on passe un **factory callable**
   `repo_factory: Callable[[Any], XRepository]` au constructeur.
   L'orchestrateur appelle `self._repo = self._repo_factory(cur)` dans
   `preload_caches()` ou au début de `run()`.

Exemple depuis `run_pipeline.py` :

```python
from infrastructure.db.queries.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

PgPersonsCreateQueries()        # adapter query service
person_repository(cur)          # factory repository
```

## Pipeline

L'orchestrateur `run_pipeline.py` à la racine enchaîne 9 phases :

1. **extract** — sources → staging (JSONB brut)
2. **cross_imports** — DOIs manquants entre sources, fetch HAL par
   hal-id / NNT
3. **normalize** — staging → tables sources (`source_publications`,
   `source_persons`, `source_authorships`). Rattachement aux
   publications existantes par DOI/NNT/HAL-ID, **sans création**
4. **affiliations** — adresses → structures, propagation
   `in_perimeter` et `structure_ids` sur `source_authorships`
5. **publications** — création publications pour les
   source_publications in-perimeter non rattachées + merges
   inter-sources (HAL-ID, NNT)
6. **persons** — création/mapping personnes + formes de noms
7. **authorships** — reconstruction authorships canoniques (table de
   vérité) + propagation UCA
8. **countries** — détection pays des adresses + recalcul pays des
   publications
9. **enrich** — OA status via Unpaywall, APC revues

Chaque phase est idempotente (relançable sans risque). Reprise depuis
une phase donnée : `python run_pipeline.py --from <phase>`.

Voir [pipeline.md](pipeline.md) pour le détail par phase.

## Tests

- **Unit** (`tests/unit/`) — pas de DB. Couvre `domain/`,
  `application/` (services avec mocks), parsing des normalizers,
  infrastructure pure (log, pipeline_metrics).
- **Intégration** (`tests/integration/`) — base `bibliometrie_test`
  créée à la volée, fixture `db` avec rollback entre chaque test.
  Couvre les routers, les orchestrateurs pipeline, et les adapters
  repositories.

Conftest splitté :
- `tests/conftest.py` — cross-cutting (mock `setup_logger` pour
  éviter la pollution disque, caches)
- `tests/integration/conftest.py` — setup BDD, fixture `db`

Couverture actuelle ~49%, seuil `fail_under = 49`
(`[tool.coverage.report]` dans `pyproject.toml`).

## Composition roots

Les endroits qui câblent le tout (instanciation concrète des adapters,
passage aux services/orchestrateurs) :

- `interfaces/api/app.py` + les routers — API HTTP
- `run_pipeline.py` — orchestrateur pipeline (appelle directement les
  phases `application/pipeline/*` avec les `Pg*Queries` concrets)
- `interfaces/cli/pipeline/*` — entry points CLI pour chaque phase
  (lancés ponctuellement hors pipeline complet)
- `interfaces/cli/*` — scripts one-shot

Aucun autre endroit ne doit importer `infrastructure.repositories` ou
`infrastructure.db.queries` : ce sont les seuls points où le domaine
rencontre ses implémentations concrètes.

## Pour aller plus loin

- [ROADMAP.md](../ROADMAP.md) — état des chantiers architecture,
  points d'audit périodique
- [donnees.md](donnees.md) — modèle de données
- [pipeline.md](pipeline.md) — détail des phases
- [sources.md](sources.md) — API et imports par source
