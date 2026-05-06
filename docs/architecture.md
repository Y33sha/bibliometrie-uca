# Architecture logicielle — Bibliométrie UCA

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

4. **Adapters entrants ⊥ adapters sortants.** Les routers FastAPI et
   scripts CLI (`interfaces/api/routers/*`, `interfaces/cli/*` hors
   composition root) **ne doivent pas** importer `infrastructure/`
   directement. Ils pilotent des use-cases applicatifs et reçoivent
   leurs dépendances ; ils ne les construisent pas. *État actuel :
   cible non encore atteinte, cf. ROADMAP §1.6 — les routers
   instancient encore directement certaines factories de
   repositories.*

5. **Le composition root est un endroit précis.** L'instanciation
   concrète des adapters et leur câblage aux use-cases se fait
   dans **un petit ensemble nommé de fichiers** :

   - `interfaces/api/app.py` + `interfaces/api/async_deps.py` — API HTTP
   - `run_pipeline.py` — pipeline complet
   - `interfaces/cli/pipeline/*` — phases pipeline isolées
   - `interfaces/cli/*` — scripts one-shot

   Ces fichiers sont les **seuls** qui ont légitimement le droit
   d'importer `infrastructure.repositories`, `infrastructure.db.queries.*`
   ou toute classe `Pg*` concrète. Partout ailleurs, on passe par un
   port.

Le contrat `layers` d'`import-linter` (voir `pyproject.toml`,
section `[tool.importlinter]`) vérifie aujourd'hui les règles 1 à 3.
Les règles 4 et 5 seront verrouillables quand §1.6 de la ROADMAP
sera clôturé (durcissement prévu du contrat pour interdire
`interfaces.api.routers.* → infrastructure.*`).

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
   `Address`, `Perimeter`).
2. **La signature ne référence que des types `domain/`, stdlib, ou
   primitives Python** (`int`, `str`, `dict`, `list`, etc.). Aucun
   type d'`infrastructure/`, aucun `cur: Cursor`, aucun fragment SQL.
3. **Les méthodes sont nommées en termes métier** (`find_by_doi`,
   `create`, `merge_into`), pas en termes techniques (`execute_query`,
   `fetch_batch`, `count_table`).

Sinon, le port va dans **`application/ports/`** : c'est un query
service ou un wrapper d'opération orchestrationnelle, propre à un
workflow applicatif (phase pipeline, etc.) plutôt qu'à un agrégat.
Les ports `application/` peuvent légitimement avoir `cur: Any` dans
leurs signatures — c'est un signal qu'on est dans l'orchestration
technique, pas dans le langage du domaine.

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
`infrastructure/`**. §1.7b clôturé — zéro violation historique en
`ignore_imports`. Toute nouvelle dépendance doit passer par un port.

### `infrastructure/` — adapters sortants

Contenu :
- **`db/`** :
  - `schema.sql`, `seed.sql`
  - `migrations/` — migrations numérotées, appliquées via
    `python -m infrastructure.db.migrate`
  - `queries/` — query services SQL (un par agrégat ou phase
    pipeline) ; implémentent les ports définis dans `application/
    ports/*`
  - `connection.py` / `async_connection.py` — pools psycopg3 (sync
    pour pipeline/CLI, async pour l'API FastAPI)
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

Le composition root est l'endroit où les adapters concrets sont
**instanciés** et **câblés** aux use-cases. Il a, par nature, le
droit d'importer `infrastructure.*` directement — c'est son rôle.
Partout ailleurs, on reçoit un port en paramètre.

Les fichiers qui jouent ce rôle :

- `interfaces/api/app.py` — entry point FastAPI (startup, lifespan,
  montage des routers)
- `interfaces/api/async_deps.py` — factories partagées par les
  routers (`get_async_cursor`, `get_root_structure_id`,
  `get_perimeter_queries`, …)
- `run_pipeline.py` — orchestrateur pipeline complet
- `interfaces/cli/pipeline/*` — entry points CLI pour chaque phase
- `interfaces/cli/*` — scripts one-shot

Cible (ROADMAP §1.6) : **seuls** ces fichiers importent
`infrastructure.repositories`, `infrastructure.db.queries.*` ou toute
classe `Pg*` concrète. Les routers et CLI applicatifs reçoivent
leurs dépendances, ne les construisent pas. En attendant, quelques
routers instancient encore des factories directement — dette
résiduelle listée dans la roadmap.

## Pour aller plus loin

- [ROADMAP.md](../ROADMAP.md) — état des chantiers architecture,
  points d'audit périodique
- [donnees.md](donnees.md) — modèle de données
- [pipeline.md](pipeline.md) — détail des phases
- [sources.md](sources.md) — API et imports par source
