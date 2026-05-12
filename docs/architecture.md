# Architecture logicielle — Bibliométrie UCA

*Document à jour au 2026-05-11.*

Pour le modèle de données (tables, relations, domaines fonctionnels),
voir [donnees.md](donnees.md).

## Vue d'ensemble

Le projet suit une architecture **hexagonale (DDD)**. Le cœur du
système est `application/` (use-cases et orchestrateurs), qui
dépend de `domain/` (noyau pur). Autour de ce cœur, deux bandes
périphériques d'**adapters frères** qui ne se connaissent pas :
`interfaces/` (adapters entrants — HTTP, CLI) et `infrastructure/`
(adapters sortants — DB, APIs externes, logs, settings). La
neutralité entre ces deux bandes repose sur les **ports**
(`Protocol`) définis dans `application/ports/` ou `domain/ports/`,
qui forment une zone neutre dont dépendent tous les autres modules.

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

**Règles dures.**

1. **Noyau pur.** `domain/` contient zéro I/O, zéro import externe
   hormis `stdlib`. Testable sans DB, sans HTTP, sans mock, en
   millisecondes.

2. **Les ports sont une zone neutre.** `application/ports/*` (ports
   des query services et adapters spécifiques) et `domain/ports/*`
   (ports repositories d'agrégats) ne contiennent que des Protocol,
   pas d'implémentation. Tous les autres modules dépendent d'eux ;
   eux ne dépendent de personne (sauf `domain/` pour les types
   métier).

3. **Use-cases ⊥ adapters sortants.** `application/*.py` (hors
   `ports/`) et `infrastructure/` sont frères : aucun import mutuel.
   Les deux dépendent des ports. Contrôlé par `import-linter`
   (contrat `layered` dans `pyproject.toml`).

4. **Routers ⊥ adapters sortants.** Les routers FastAPI
   (`interfaces/api/routers/*`) **ne doivent pas** importer
   `infrastructure/` directement. Ils pilotent des use-cases
   applicatifs et reçoivent leurs dépendances via `Depends(...)`
   (factories dans `interfaces.api.deps`) ; ils ne les construisent
   pas. Verrouillé par le contrat `import-linter` "Routers : pas
   d'import direct de infrastructure". Trois exceptions documentées :
   `auth.py` lit `infrastructure.settings` (config statique),
   `admin_pipeline.py` appelle `infrastructure.pipeline_status`
   (status filesystem), `docs.py` utilise `infrastructure.PROJECT_ROOT`
   (chemin projet) — aucune ne touche à la DB. Les scripts CLI ne
   sont pas concernés par cette règle : ils sont des composition
   roots (cf. règle 5).

5. **Le composition root est un endroit précis.** L'instanciation
   concrète des adapters et leur câblage aux use-cases se fait
   dans **un petit ensemble nommé de fichiers** :

   - `interfaces/api/app.py` + `interfaces/api/deps.py` — API HTTP
   - `run_pipeline.py` — pipeline complet
   - `interfaces/cli/pipeline/*` — phases pipeline isolées
   - `interfaces/cli/*` — scripts one-shot

   Ces fichiers sont les **seuls** qui ont légitimement le droit
   d'importer `infrastructure.repositories`, `infrastructure.db.queries.*`
   ou toute classe `Pg*` concrète. Partout ailleurs, on passe par un
   port.

Le contrat `layers` d'`import-linter` (voir `pyproject.toml`,
section `[tool.importlinter]`) vérifie les règles 1 à 3. Le contrat
`forbidden` "Routers : pas d'import direct de infrastructure" applique
la règle 4. La règle 5 reste discipline-only.

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
  `ConfigRepository`, `PublisherRepository`

Le domaine est testé en unit sans DB.

#### Règle de placement des ports : `domain/ports/` vs `application/ports/`

Un port va dans **`domain/ports/`** ssi les **trois critères** sont
remplis simultanément :

1. **Le port représente la persistance d'un agrégat du domaine**
   (entité racine identifiable au cœur du modèle métier : `Person`,
   `Publication`, `Structure`, `Authorship`, `Journal`, `Publisher`,
   `Address`, `Perimeter`, `Audit`).
2. **La signature ne référence que des types `domain/`, stdlib, ou
   primitives Python** (`int`, `str`, `dict`, `list`, etc.). Aucun
   type d'`infrastructure/`, aucun fragment SQL.
3. **Les méthodes sont nommées en termes métier** (`find_by_doi`,
   `create`, `merge_into`), pas en termes techniques (`execute_query`,
   `fetch_batch`, `count_table`).

Sinon, le port va dans **`application/ports/`** : c'est un query
service ou un wrapper d'opération orchestrationnelle, propre à un
workflow applicatif (phase pipeline, etc.) plutôt qu'à un agrégat.
Les ports `application/` ont typiquement une signature qui prend
explicitement une `Connection` SA en premier argument — signal qu'on
est dans l'orchestration technique, pas dans le langage du domaine.

**Le critère est conceptuel, pas mécanique** (« est-ce que ce port
parle du domaine ? »), pas (« est-ce que ce port est utilisé par
`domain/` ? ») : ce dernier critère, appliqué strictement, viderait
`domain/ports/` puisque le domaine ne fait pas d'I/O et n'utilise donc
jamais directement un port. C'est `application/` qui consomme les
ports `domain/` dans les use cases.

**Exceptions assumées** :
- `address_repository` expose des méthodes de propagation
  cross-aggregate (ex. `refresh_publications_countries_for_addresses`)
  qui touchent `publications.countries`. Pattern accepté en DDD quand
  les agrégats sont étroitement liés et que la propagation fait
  partie de la cohérence métier.

### `application/` — services et orchestrateurs

Contenu :
- **Services métier** : `persons.py`, `publications.py`, `journals.py`,
  `authorships/core.py`, `authorships/assign_orphans.py`,
  `structures.py`, `addresses_countries.py`, `addresses_structures.py`,
  `audit.py`, `config.py`, `publishers.py`. Ces services reçoivent
  leurs dépendances par injection (kwarg `repo=`, `audit_repo=`,
  `queries=`).
- **Orchestrateurs pipeline** dans `application/pipeline/` :
  - `normalize/` — staging → tables sources (un module par source)
  - `affiliations/` — propagation adresses ↔ structures vers
    `source_authorships.in_perimeter` / `structure_ids`
  - `publications/` — création/merge publications canoniques
  - `persons/` — création personnes + formes de noms
  - `authorships/` — reconstruction de la table de vérité
  - `countries/` — recalcul pays publications
  - `subjects/` — ingestion sujets/mots-clés
  - `cooccurrences/` — recalcul co-occurrences sujets
  - `enrich/` — Unpaywall, APC
  - `fetch_missing_doi.py` — cross-source DOI lookup
- **Ports** (`application/ports/*`) : interfaces Protocol pour les
  query services (adapters dans `infrastructure/db/queries/*`).

Interdiction : **`application/` ne peut pas importer
`infrastructure/`**. Toute nouvelle dépendance doit passer par un
port. Vérifié par le contrat `layered` d'`import-linter`.

### `infrastructure/` — adapters sortants

Contenu :
- **`db/`** :
  - `schema.sql` (snapshot descriptif, régénéré par
    `python -m infrastructure.db.dump_schema`), `seed.sql`
  - `tables.py` — MetaData SQLAlchemy explicite (source pour
    `alembic revision --autogenerate`). Les migrations vivent dans
    `alembic/versions/` à la racine, appliquées via
    `alembic upgrade head`.
  - `queries/` — query services SQL (un par agrégat ou phase
    pipeline) ; implémentent les ports définis dans `application/
    ports/*`
  - `engine.py` — Engine SQLAlchemy synchrone (driver
    `postgresql+psycopg`). Source unique pour l'API FastAPI (via le
    threadpool Starlette) et le pipeline.
  - `connection.py` — réduit à des constantes communes
    (`SANDBOX_DB_NAME`) ; la fonction `get_connection()` n'est plus
    utilisée par le code applicatif depuis l'adoption SA.
- **`repositories/`** — adapters PostgreSQL implémentant les ports
  `domain/ports/*` : `person_repository/`, `publication_repository.py`,
  `journal_repository.py`, `structure_repository.py`,
  `authorship_repository.py`, `address_repository.py`,
  `publisher_repository.py`, `perimeter_repository.py`,
  `audit_repository.py`. Factories exposées dans `__init__.py`
  (`person_repository(conn)`, `publication_repository(conn)`, …).
- **`sources/`** — extracteurs API (HAL, OpenAlex, WoS, ScanR,
  theses.fr, Crossref). Héritent de `SourceExtractor` (`base.py`).
- **Divers** : `log.py` (JSON structuré), `settings.py`
  (pydantic-settings), `perimeter.py`, `addresses.py`, `zenodo.py`,
  `api_retry.py`, `api_limits.py`, `pipeline_metrics.py`,
  `pipeline_status.py`, `app_config.py`, `db/dump_schema.py`.

Interdiction : **`infrastructure/` ne peut pas importer
`application/`** (sauf par un port explicitement passé).

### `interfaces/` — adapters entrants

Contenu :
- **`api/`** — FastAPI :
  - `app.py` — entry point (routers, middlewares, gestion d'erreurs)
  - `routers/` — un module par agrégat (publications, persons,
    laboratories, addresses, …)
  - `models.py` — Pydantic pour les bodies POST/PUT/PATCH
  - `deps.py` — dépendances (Engine SA sync, factories de query
    services et de repositories, auth)
  - middlewares inline dans `app.py` (auth, strip-prefix, timing)
- **`frontend/`** — SvelteKit (Svelte 5)
- **`cli/`** — scripts one-shot (imports manuels, debug, corrections
  ponctuelles). Exclus de la couverture pytest
  (`[tool.coverage.run]` omit).

## Patterns d'injection

### Sync partout (FastAPI + threadpool)

Toutes les routes API sont déclarées `def` (pas `async def`). FastAPI
les exécute dans le threadpool Starlette (~40 workers par défaut), ce
qui permet de partager **les mêmes** repositories et query services
entre l'API et le pipeline. Une seule famille de code, un seul style
de connexion (`Connection` SQLAlchemy).

L'unique exception : `feedback_rerun` dans `admin_feedback.py` reste
`async def` parce qu'il streame du SSE depuis un subprocess
(`asyncio.create_subprocess_exec` + `StreamingResponse`). Aucune
connexion DB en jeu, cohabitation supportée par FastAPI.

Dimensionnement du pool DB : `db_pool_max = 30` (dans
`infrastructure/settings.py`), pour absorber confortablement la
concurrence threadpool × marge sur un usage admin
(quelques utilisateurs concurrents max). Bumper si on observe des
`TimeoutError` côté pool sous charge anormale (cf. `.env.example`).

### Services applicatifs ↔ repositories

Les services acceptent leur repo (et autres dépendances : audit_repo,
queries, …) en kwarg keyword-only :

```python
def set_rejected(
    person_id: int,
    rejected: bool,
    *,
    repo: PersonRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    repo.set_rejected(person_id, rejected)
    emit_event(audit_repo, "person.rejected", ...)
```

Les callers directs (routers, tests, scripts CLI) créent l'instance
via la factory :

```python
from infrastructure.repositories import person_repository
set_rejected(person_id, True, repo=person_repository(conn))
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
   `repo_factory: Callable[[Connection], XRepository]` au constructeur.
   L'orchestrateur appelle `self._repo = self._repo_factory(conn)` dans
   `preload_caches()` ou au début de `run()`.

Exemple depuis `run_pipeline.py` :

```python
from infrastructure.db.queries.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

PgPersonsCreateQueries()        # adapter query service
person_repository(conn)         # factory repository
```

## Pipeline

L'orchestrateur `run_pipeline.py` à la racine enchaîne 12 phases :

1. **extract** — sources → staging (JSONB brut)
2. **fetch_missing_hal_id** — récupère les notices HAL manquantes
   par hal-id / NNT pour les sources externes
3. **fetch_missing_doi** — cross-source DOI lookup
4. **normalize** — staging → tables sources (`source_publications`,
   `source_persons`, `source_authorships`). Rattachement aux
   publications existantes par DOI/NNT/HAL-ID, **sans création**
5. **affiliations** — adresses → structures, propagation
   `in_perimeter` et `structure_ids` sur `source_authorships`
6. **publications** — création publications pour les
   source_publications in-perimeter non rattachées + merges
   inter-sources (HAL-ID, NNT)
7. **persons** — création/mapping personnes + formes de noms
8. **authorships** — reconstruction authorships canoniques (table de
   vérité) + propagation UCA
9. **countries** — détection pays des adresses + recalcul pays des
   publications
10. **subjects** — ingestion sujets/mots-clés depuis
    `source_publications.keywords` / `topics` vers `subjects` et
    `publication_subjects`
11. **cooccurrences** — recalcul de la table `subject_cooccurrences`
12. **enrich** — OA status via Unpaywall, APC revues

Chaque phase est idempotente (relançable sans risque). Reprise depuis
une phase donnée : `python run_pipeline.py --from <phase>`.

Voir [pipeline.md](pipeline) pour le détail par phase.

## Tests

- **Unit** (`tests/unit/`) — pas de DB. Couvre `domain/`,
  `application/` (services avec mocks), parsing des normalizers,
  infrastructure pure (log, pipeline_metrics).
- **Intégration** (`tests/integration/`) — base `bibliometrie_test`
  créée à la volée (`alembic upgrade head` sur DB vierge), fixtures
  `db` (curseur psycopg avec rollback) et `sa_sync_conn` (Connection
  SA avec rollback). Couvre les routers, les orchestrateurs pipeline,
  et les adapters repositories.

Conftest splitté :
- `tests/conftest.py` — cross-cutting (mock `setup_logger` pour
  éviter la pollution disque, caches)
- `tests/integration/conftest.py` — setup BDD via Alembic, fixtures
  `db` / `sa_sync_conn`

Seuil de couverture `fail_under = 62` (`[tool.coverage.report]` dans
`pyproject.toml`).

## Composition roots

Le composition root est l'endroit où les adapters concrets sont
**instanciés** et **câblés** aux use-cases. Il a, par nature, le
droit d'importer `infrastructure.*` directement — c'est son rôle.
Partout ailleurs, on reçoit un port en paramètre.

Les fichiers qui jouent ce rôle :

- `interfaces/api/app.py` — entry point FastAPI (startup, lifespan,
  middlewares, montage des routers)
- `interfaces/api/deps.py` — factories partagées par les routers :
  `db_conn_sync` (Connection SA), query services et repositories
  câblés sur cette Connection
- `run_pipeline.py` — orchestrateur pipeline complet
- `interfaces/cli/pipeline/*` — entry points CLI pour chaque phase
- `interfaces/cli/*` — scripts one-shot

**Seuls** ces fichiers importent `infrastructure.repositories`,
`infrastructure.db.queries.*` ou toute classe `Pg*` concrète.

- **Côté API** : `app.py` / `deps.py` sont les composition roots ;
  les routers individuels (`interfaces/api/routers/*`) reçoivent
  leurs dépendances via `Depends(...)` et **n'importent pas**
  `infrastructure.*` directement. Verrouillé par le contrat
  `import-linter` "Routers : pas d'import direct de infrastructure".
- **Côté CLI** : chaque script (`interfaces/cli/*`, y compris
  `interfaces/cli/pipeline/*`) **est** son propre composition root.
  Il importe les adapters concrets, instancie les factories, et
  appelle un use case applicatif en lui passant tout en kwargs.
  Pas de séparation construct/appel comme côté API ; cohérent avec
  la nature one-shot des scripts. Pas de contrat `import-linter`
  côté CLI, la discipline reste manuelle : `application/` et
  `domain/` ne doivent jamais importer `infrastructure/`, et le
  script CLI doit rester un thin wrapper (imports + instanciations
  + appel d'un use case ; pas de logique métier dans le script).

## Pour aller plus loin

- [donnees.md](donnees) — modèle de données
- [pipeline.md](pipeline) — détail des phases
- [sources.md](sources) — API et imports par source
